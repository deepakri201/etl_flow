#
# Copyright 2015-2021, Institute for Systems Biology
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

import time
from datetime import datetime, timedelta
import logging
from uuid import uuid4
from idc.models import Version, Collection, Patient
from ingestion.utils import accum_sources, empty_bucket, create_prestaging_bucket
from ingestion.patient import clone_patient, build_patient, retire_patient
from ingestion.all_sources import All
from ingestion.mtm.sources_mtm import All_mtm
from utilities.get_collection_dois import get_data_collection_doi, get_analysis_collection_dois
from utilities.tcia_helpers import get_access_token

from python_settings import settings

from multiprocessing import Process, Queue, Lock, shared_memory
from queue import Empty

from sqlalchemy.orm import Session
from sqlalchemy_utils import register_composites
from sqlalchemy import create_engine

rootlogger = logging.getLogger('root')
errlogger = logging.getLogger('root.err')


def clone_collection(collection,uuid):
    new_collection = Collection(uuid=uuid)
    for key, value in collection.__dict__.items():
        if key not in ['_sa_instance_state', 'uuid', 'versions', 'patients']:
            setattr(new_collection, key, value)
    for patient in collection.patients:
        new_collection.patients.append(patient)
    return new_collection


def retire_collection(args, collection):
    # If this object has children from source, delete them
    rootlogger.debug('p%s: Collection %s retiring', args.id, collection.collection_id)
    for patient in collection.patients:
        retire_patient(args, patient)
    collection.final_idc_version = args.previous_version


PATIENT_TRIES=5
def worker(input, output, args, data_collection_doi, analysis_collection_dois, access, lock):
    # rootlogger.debug('p%s: Worker starting: args: %s', args.id, args)
    sql_engine = create_engine(args.sql_uri)
    with Session(sql_engine) as sess:

        if args.build_mtm_db:
            # When build the many-to-many DB, we mine some existing one to many DB
            sql_uri_mtm = f'postgresql+psycopg2://{settings.CLOUD_USERNAME}:{settings.CLOUD_PASSWORD}@{settings.CLOUD_HOST}:{settings.CLOUD_PORT}/idc_v{args.version}'
            sql_engine_mtm = create_engine(sql_uri_mtm)
            conn_mtm = sql_engine_mtm.connect()
            register_composites(conn_mtm)
            # Use this to see the SQL being sent to PSQL
            all_sources = All_mtm(sess, Session(sql_engine_mtm), args.version)
        else:
            all_sources = All(args.id, sess, args.version, access, lock)
        # all_sources.lock = lock
        # rootlogger.info('p%s: Lock: _rand %s, _sem_lock: %s', args.id, list(all_sources.sources.values())[0].lock._rand, list(all_sources.sources.values())[0].lock._semlock)
        # rootlogger.info('p%s: access token: %s, refresh token: %s', args.id, list(all_sources.sources.values())[0].access_token, list(all_sources.sources.values())[0].refresh_token)

        for more_args in iter(input.get, 'STOP'):
            for attempt in range(PATIENT_TRIES):
                time.sleep((2**attempt)-1)
                index, collection_id, submitter_case_id = more_args
                try:
                    version = sess.query(Version).filter(Version.version==args.version).one()
                    collection = next(collection for collection in version.collections if collection.collection_id ==collection_id)
                    patient = next(patient for patient in collection.patients if patient.submitter_case_id==submitter_case_id)
                    # rootlogger.debug("p%s: In worker, sess: %s, submitter_case_id: %s", args.id, sess, submitter_case_id)
                    build_patient(sess, args, all_sources, index, data_collection_doi, analysis_collection_dois, version, collection, patient)
                    break
                except Exception as exc:
                    errlogger.error("p%s, exception %s; reattempt %s on patient %s/%s, %s; %s", args.id, exc, attempt, collection.collection_id, patient.submitter_case_id, index, time.asctime())
                    sess.rollback()

            if attempt == PATIENT_TRIES:
                errlogger.error("p%s, Failed to process patient: %s", args.id, patient.submitter_case_id)
                sess.rollback()
            output.put(patient.submitter_case_id)


def expand_collection(sess, args, all_sources, collection):
    if not args.build_mtm_db:
        # Since we are starting, delete everything from the prestaging bucket.
        rootlogger.info("Emptying prestaging bucket")
        begin = time.time()
        create_prestaging_bucket(args)
        empty_bucket(args.prestaging_bucket)
        # Since we are starting, delete everything from the prestaging bucket.
        duration = str(timedelta(seconds=(time.time() - begin)))
        rootlogger.info("Emptying prestaging bucket completed in %s", duration)

    # Get the patients that the sources know about
    # Returned data includes a sources vector for each patient
    patients = all_sources.patients(collection)

    # Check for duplicates
    if len(patients) != len(set(patients)):
        errlogger.error("  p%s: Duplicate patients in expansion of collection %s", args.id,
                        collection.collection_id)
        raise RuntimeError("p%s: Duplicate patients expansion of collection %s", args.id,
                           collection.collection_id)
    if collection.is_new:
        # All patients are new by definition
        new_objects = patients
        retired_objects = []
        existing_objects = []
    else:
        # Get the IDs of the patients that we have.
        idc_objects = {object.submitter_case_id: object for object in collection.patients}

        new_objects = sorted([id for id in patients if id not in idc_objects])
        retired_objects = sorted([idc_objects[id] for id in idc_objects if id not in patients], key=lambda patient: patient.submitter_case_id)
        existing_objects = sorted([idc_objects[id] for id in idc_objects if id in patients], key=lambda patient: patient.submitter_case_id)

    for patient in sorted(new_objects):
        new_patient = Patient()

        new_patient.submitter_case_id = patient
        if args.build_mtm_db:
            new_patient.idc_case_id = patients[patient]['idc_case_id']
            new_patient.min_timestamp = patients[patient]['min_timestamp']
            new_patient.max_timestamp = patients[patient]['max_timestamp']
            new_patient.sources = patients[patient]['sources']
            new_patient.hashes = patients[patient]['hashes']
            new_patient.revised = False
        else:
            new_patient.idc_case_id = str(uuid4())
            new_patient.min_timestamp = datetime.utcnow()
            new_patient.revised = patients[patient]
            new_patient.sources = (False, False)
            new_patient.hashes = None
        new_patient.uuid = str(uuid4())
        new_patient.max_timestamp = new_patient.min_timestamp
        new_patient.init_idc_version=args.version
        new_patient.rev_idc_version=args.version
        new_patient.final_idc_version=0
        new_patient.done=False
        new_patient.is_new=True
        new_patient.expanded=False

        collection.patients.append(new_patient)
        rootlogger.debug('  p%s: Patient %s is new',  args.id, new_patient.submitter_case_id)

    for patient in existing_objects:
        idc_hashes = patient.hashes
        src_hashes = all_sources.src_patient_hashes(collection.collection_id, patient.submitter_case_id)
        revised = [x != y for x, y in zip(idc_hashes[:-1], src_hashes)]
        if any(revised):
            # rootlogger.debug('p%s **Revising patient %s', args.id, patient.submitter_case_id)
            # Mark when we started work on this patient
            # assert args.version == patients[patient.submitter_case_id]['rev_idc_version']
            rev_patient = clone_patient(patient, str(uuid4()))
            rev_patient.done = False
            rev_patient.is_new = False
            rev_patient.expanded = False
            if args.build_mtm_db:
                rev_patient.min_timestamp = patients[patient.submitter_case_id]['min_timestamp']
                rev_patient.max_timestamp = patients[patient.submitter_case_id]['max_timestamp']
                rev_patient.hashes = patients[patient.submitter_case_id]['hashes']
                rev_patient.rev_idc_version = patients[patient.submitter_case_id]['rev_idc_version']
                rev_patient.revised = True
            else:
                rev_patient.revised = revised
                rev_patient.hashes = None
                rev_patient.sources = [False, False]
                rev_patient.rev_idc_version = args.version
            collection.patients.append(rev_patient)
            rootlogger.debug('  p%s: Patient %s is revised',  args.id, rev_patient.submitter_case_id)

            # Mark the now previous version of this object as having been replaced
            # and drop it from the revised collection
            patient.final_idc_version = args.previous_version
            collection.patients.remove(patient)

        else:
            # The patient is unchanged. Just add it to the collection
            if not args.build_mtm_db:
                # Stamp this series showing when it was checked
                patient.min_timestamp = datetime.utcnow()
                patient.max_timestamp = datetime.utcnow()
                # Make sure the collection is marked as done and expanded
                # Shouldn't be needed if the previous version is done

                patient.done = True
                patient.expanded = True
            rootlogger.debug('  p%s: Patient %s unchanged',  args.id, patient.submitter_case_id)

    for patient in retired_objects:
        breakpoint()
        # rootlogger.debug('  p%s: Patient %s retiring', args.id, patient.submitter_case_id)
        retire_patient(args, patient)
        collection.patients.remove(patient)


    collection.expanded = True
    sess.commit()
    return
    # rootlogger.debug("p%s: Expanded collection %s",args.id, collection.collection_id)


def build_collection(sess, args, all_sources, collection_index, version, collection):
    begin = time.time()
    rootlogger.debug("p%s: Expand Collection %s, %s", args.id, collection.collection_id, collection_index)
    args.prestaging_bucket = f"{args.prestaging_bucket_prefix}{collection.collection_id.lower().replace(' ','_').replace('-','_')}"
    if not collection.expanded:
        expand_collection(sess, args, all_sources, collection)
    rootlogger.info("p%s: Expanded Collection %s, %s, %s patients", args.id, collection.collection_id, collection_index, len(collection.patients))
    if not args.build_mtm_db:
        # Get the lists of data and analyis series for this collection
        data_collection_doi = get_data_collection_doi(collection.collection_id, server=args.server)
        if data_collection_doi=="":
            if collection.collection_id=='NLST':
                data_collection_doi = '10.7937/TCIA.hmq8-j677'
            elif collection.collection_id == 'Pancreatic-CT-CBCT-SEG':
                data_collection_doi = '10.7937/TCIA.ESHQ-4D90'
            elif collection.collection_id == 'CPTAC-LSCC':
                data_collection_doi = '10.7937/K9/TCIA.2018.6EMUB5L2'
            elif collection.collection_id == 'CPTAC-AML':
                data_collection_doi = '10.7937/tcia.2019.b6foe619'
            elif collection.collection_id == 'CPTAC-BRCA':
                data_collection_doi = '10.7937/TCIA.CAEM-YS80'
            elif collection.collection_id == 'CPTAC-COAD':
                data_collection_doi = '10.7937/TCIA.YZWQ-ZZ63'
            elif collection.collection_id == 'CPTAC-OV':
                data_collection_doi = '10.7937/TCIA.ZS4A-JD58'
            else:
                errlogger.error('No DOI for collection %s', collection.collection_id)
                pass
                # return
        pre_analysis_collection_dois = get_analysis_collection_dois(collection.collection_id, server=args.server)
        analysis_collection_dois = {x['SeriesInstanceUID']: x['SourceDOI'] for x in pre_analysis_collection_dois}
    else:
        data_collection_doi = ""
        analysis_collection_dois = {}

    if args.num_processes==0:
        # for series in sorted_seriess:
        for patient in collection.patients:
            patient_index = f'{collection.patients.index(patient) + 1} of {len(collection.patients)}'
            if not patient.done:
                build_patient(sess, args, all_sources, patient_index, data_collection_doi, analysis_collection_dois, version, collection, patient)
            else:
                if True:
                    rootlogger.info("  p%s: Patient %s, %s, previously built", args.id, patient.submitter_case_id,
                                patient_index)

    else:
        processes = []
        # Create queues
        task_queue = Queue()
        done_queue = Queue()

        # List of patients enqueued
        enqueued_patients = []

        num_processes = min(args.num_processes, len(collection.patients))

        # Start worker processes
        lock = Lock()
        for process in range(num_processes):
            args.id = process+1
            processes.append(
                Process(target=worker, args=(task_queue, done_queue, args, data_collection_doi, analysis_collection_dois, args.access, lock )))
            processes[-1].start()

        # Enqueue each patient in the the task queue
        args.id = 0
        patients = sorted(collection.patients, key=lambda patient: patient.done, reverse=True)
        for patient in patients:
            patient_index = f'{collection.patients.index(patient) + 1} of {len(collection.patients)}'
            if not patient.done:
                # task_queue.put((patient_index, version.idc_version_number, collection.collection_id, patient.submitter_case_id))
                task_queue.put((patient_index, collection.collection_id, patient.submitter_case_id))
                enqueued_patients.append(patient.submitter_case_id)
            else:
                if (collection.patients.index(patient) % 100 ) == 0:
                    rootlogger.info("  p%s: Patient %s, %s, previously built", args.id, patient.submitter_case_id,
                                patient_index)

        # Collect the results for each patient
        try:
            while not enqueued_patients == []:
                # Timeout if waiting too long
                results = done_queue.get(True)
                enqueued_patients.remove(results)

            # Tell child processes to stop
            for process in processes:
                task_queue.put('STOP')

            # Wait for them to stop
            for process in processes:
                process.join()

            sess.commit()

        except Empty as e:
            errlogger.error("Timeout in build_collection %s", collection.collection_id)
            for process in processes:
                process.terminate()
                process.join()
            sess.rollback()
            duration = str(timedelta(seconds=(time.time() - begin)))
            rootlogger.info("Collection %s, %s, NOT completed in %s", collection.collection_id, collection_index,
                            duration)

    if all([patient.done for patient in collection.patients]):
        collection.max_timestamp = max([patient.max_timestamp for patient in collection.patients if patient.max_timestamp != None])

        if args.build_mtm_db:
            collection.done = True
            sess.commit()
            duration = str(timedelta(seconds=(time.time() - begin)))
            rootlogger.info("Completed Collection %s, %s, in %s", collection.collection_id, collection_index,
                        duration)
        else:

            try:
                # Get a list of what DB thinks are the collection's hashes
                idc_hashes = all_sources.idc_collection_hashes(collection)
                # Get a list of what the sources think are the collection's hashes
                src_hashes = all_sources.src_collection_hashes(collection.collection_id)
                # They must be the same
                if src_hashes != idc_hashes[:-1]:
                    errlogger.error('Hash match failed for collection %s', collection.collection_id)
                else:
                    collection.hashes = idc_hashes
                    collection.sources = accum_sources(collection, collection.patients)
                    collection.done = True
                    sess.commit()
                duration = str(timedelta(seconds=(time.time() - begin)))
                rootlogger.info("Completed Collection %s, %s, in %s", collection.collection_id, collection_index,
                                duration)
            except Exception as exc:
                errlogger.error('Could not validate collection hash for %s: %s', collection.collection_id, exc)

    else:
        duration = str(timedelta(seconds=(time.time() - begin)))
        rootlogger.info("Collection %s, %s, not completed in %s", collection.collection_id, collection_index,
                        duration)
