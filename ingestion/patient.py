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
from idc.models import Patient, Study
from ingestion.utils import accum_sources, get_merkle_hash
from ingestion.study import clone_study, build_study, retire_study

rootlogger = logging.getLogger('root')
errlogger = logging.getLogger('root.err')


def clone_patient(patient, uuid):
    new_patient = Patient(uuid=uuid)
    for key, value in patient.__dict__.items():
        if key not in ['_sa_instance_state', 'uuid', 'collections', 'studies']:
            setattr(new_patient, key, value)
    for study in patient.studies:
        new_patient.studies.append(study)
    return new_patient


def retire_patient(args, patient):
    # If this object has children from source, delete them
    rootlogger.debug  ('  p%s: Patient %s retiring', args.id, patient.submitter_case_id)
    for study in patient.studies:
        retire_study(args, study)
    patient.final_idc_version = args.previous_version


def expand_patient(sess, args, all_sources, patient):
    # Get the studies that the sources know about
    studies = all_sources.studies(patient)    # patient_ids = [patient['PatientId'] for patient in patients]

    if len(studies) != len(set(studies)):
        errlogger.error("\tp%s: Duplicate studies in expansion of patient %s", args.id,
                        patient.submitter_case_id)
        raise RuntimeError("p%s: Duplicate studies expansion of collection %s", args.id,
                           patient.submitter_case_i)

    if patient.is_new:
        # All patients are new by definition
        new_objects = studies
        retired_objects = []
        existing_objects = []
    else:
        # Get the IDs of the studies that we have.
        idc_objects = {object.study_instance_uid: object for object in patient.studies}

        new_objects = sorted([id for id in studies if id not in idc_objects])
        retired_objects = sorted([idc_objects[id] for id in idc_objects if id not in studies], key=lambda study: study.study_instance_uid)
        existing_objects = sorted([idc_objects[id] for id in studies if id in idc_objects], key=lambda study: study.study_instance_uid)

    for study in sorted(new_objects):
        new_study = Study()
        new_study.study_instance_uid=study
        if args.build_mtm_db:
            new_study.uuid = studies[study]['uuid']
            new_study.min_timestamp = studies[study]['min_timestamp']
            new_study.max_timestamp = studies[study]['max_timestamp']
            new_study.study_instances = studies[study]['study_instances']
            new_study.sources = studies[study]['sources']
            new_study.revised = False
            new_study.hashes = studies[study]['hashes']
        else:
            new_study.uuid = str(uuid4())
            new_study.min_timestamp = datetime.utcnow()
            new_study.study_instances = 0
            new_study.revised = studies[study]
            new_study.hashes = None
            new_study.max_timestamp = new_study.min_timestamp
        new_study.init_idc_version=args.version
        new_study.rev_idc_version=args.version
        new_study.final_idc_version=0
        new_study.done = False
        new_study.is_new=True
        new_study.expanded=False
        patient.studies.append(new_study)
        rootlogger.debug  ('    p%s: Study %s is new',  args.id, new_study.study_instance_uid)


    for study in existing_objects:
        idc_hashes = study.hashes
        src_hashes = all_sources.src_study_hashes(study.study_instance_uid)
        revised = [x != y for x, y in zip(idc_hashes[:-1], src_hashes)]
        if any(revised):
            # rootlogger.debug  ('**Patient %s needs revision', patient.submitter_case_id)
            rev_study = clone_study(study, studies[study.study_instance_uid]['uuid'] if args.build_mtm_db else str(uuid4()))
            assert args.version == studies[study.study_instance_uid]['rev_idc_version']
            rev_study.revised = True
            rev_study.done = False
            rev_study.is_new = False
            rev_study.expanded = False
            if args.build_mtm_db:
                rev_study.min_timestamp = studies[study.study_instance_uid]['min_timestamp']
                rev_study.max_timestamp = studies[study.study_instance_uid]['max_timestamp']
                rev_study.sources = studies[study.study_instance_uid]['sources']
                rev_study.hashes = studies[study.study_instance_uid]['hashes']
                rev_study.rev_idc_version = studies[study.study_instance_uid]['rev_idc_version']
            else:
                rev_study.revised = revised
                rev_study.hashes = None
                rev_study.rev_idc_version = args.version
            patient.studies.append(rev_study)
            rootlogger.debug  ('    p%s: Study %s is revised',  args.id, rev_study.study_instance_uid)

            # Mark the now previous version of this object as having been replaced
            # and drop it from the revised patient
            study.final_idc_version = args.previous_version
            patient.studies.remove(study)
        else:
            # The study is unchanged. Just add it to the patient
            if not args.build_mtm_db:
                # Stamp this study showing when it was checked
                study.min_timestamp = datetime.utcnow()
                study.max_timestamp = datetime.utcnow()
                # Make sure the collection is marked as done and expanded
                # Shouldn't be needed if the previous version is done
                study.done = True
                study.expanded = True
            rootlogger.debug  ('    p%s: Study %s unchanged',  args.id, study.study_instance_uid)

    for study in retired_objects:
        # rootlogger.debug  ('    p%s: Study %s:%s retiring', args.id, study.study_instance_uid, study.uuid)
        retire_study(args, study)
        patient.studies.remove(study)

    patient.expanded = True
    sess.commit()
    # rootlogger.debug("  p%s: Expanded patient %s",args.id, patient.submitter_case_id)
    return

def build_patient(sess, args, all_sources, patient_index, data_collection_doi, analysis_collection_dois, version, collection, patient):
    begin = time.time()
    rootlogger.debug("  p%s: Expand Patient %s, %s", args.id, patient.submitter_case_id, patient_index)
    if not patient.expanded:
        expand_patient(sess, args, all_sources, patient)
    rootlogger.info("  p%s: Expanded Patient %s, %s, %s studies, expand_time: %s, %s", args.id, patient.submitter_case_id, patient_index, len(patient.studies), time.time()-begin, time.asctime())
    for study in patient.studies:
        study_index = f'{patient.studies.index(study) + 1} of {len(patient.studies)}'
        if not study.done:
            build_study(sess, args, all_sources, study_index, version, collection, patient, study, data_collection_doi, analysis_collection_dois)
        else:
            rootlogger.info("    p%s: Study %s, %s, previously built", args.id, study.study_instance_uid, study_index)
    if all([study.done for study in patient.studies]):
        patient.max_timestamp = max([study.max_timestamp for study in patient.studies if study.max_timestamp != None])

        if args.build_mtm_db:
            patient.done = True
            sess.commit()
            duration = str(timedelta(seconds=(time.time() - begin)))
            rootlogger.info("  p%s: Completed Patient %s, %s, in %s, %s", args.id, patient.submitter_case_id,
                            patient_index, duration, time.asctime())
        else:
            # Get a list of what DB thinks are the patient's hashes
            idc_hashes = all_sources.idc_patient_hashes(patient)
            # Get a list of what the sources think are the patient's hashes
            src_hashes = all_sources.src_patient_hashes(collection.collection_id, patient.submitter_case_id)
            # They must be the same
            if  src_hashes != idc_hashes[:-1]:
                # errlogger.error('Hash match failed for patient %s', patient.submitter_case_id)
                raise Exception('Hash match failed for patient %s', patient.submitter_case_id)
            else:
                patient.hashes = idc_hashes
                patient.sources = accum_sources(patient, patient.studies)

                patient.done = True
                sess.commit()
                duration = str(timedelta(seconds=(time.time() - begin)))
                rootlogger.info("  p%s: Completed Patient %s, %s, in %s, %s", args.id, patient.submitter_case_id, patient_index, duration, time.asctime())