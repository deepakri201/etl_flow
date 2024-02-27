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

# Adds/replaces data to the idc_collection/_patient/_study/_series/_instance DB tables
# from a specified bucket.
#
# For this purpose, the bucket containing the instance blobs is gcsfuse mounted, and
# pydicom is then used to extract needed metadata.
#
# The script walks the directory hierarchy from a specified subdirectory of the
# gcsfuse mount point

from idc.models import Base, IDC_Collection, IDC_Patient, IDC_Study, IDC_Series, IDC_Instance, Collection, Patient
from preingestion.populate_idc_metadata_tables.gen_hashes import gen_hashes
from utilities.logging_config import successlogger, errlogger, progresslogger
from base64 import b64decode
from python_settings import settings
from preingestion.populate_idc_metadata_tables.validate_analysis_result import validate_analysis_result
from preingestion.populate_idc_metadata_tables.validate_original_collection import validate_original_collection
from ingestion.utilities.utils import md5_hasher

import time

from pydicom import dcmread

from sqlalchemy.orm import Session
from sqlalchemy import create_engine, update
from google.cloud import storage

import csv

import argparse
import sys

def build_instance(client, args, sess, series, instance_id, hash, size, blob_name):
    try:
        # Get the record of this instance if it exists
        instance = next(instance for instance in series.instances if instance.sop_instance_uid == instance_id)
        progresslogger.info(f'\t\t\t\tInstance {blob_name} exists')
    except StopIteration:
        instance = IDC_Instance()
        instance.sop_instance_uid = instance_id
        series.instances.append(instance)
        progresslogger.info(f'\t\t\t\tInstance {blob_name} added')
    instance.idc_version = args.version
    instance.gcs_url = f'gs://{args.src_bucket}/{blob_name}'
    instance.hash = hash
    instance.idc_version = args.version
    instance.excluded = False
    successlogger.info(blob_name)


def build_series(client, args, sess, study, series_id, instance_id, hash, size, blob_name):
    try:
        series = next(series for series in study.seriess if series.series_instance_uid == series_id)
        progresslogger.info(f'\t\t\tSeries {series_id} exists')
    except StopIteration:
        series = IDC_Series()
        series.series_instance_uid = series_id
        series.third_party = args.third_party
        series.license_url =args.license['license_url']
        series.license_long_name =args.license['license_long_name']
        series.license_short_name =args.license['license_short_name']
        series.third_party = args.third_party
        study.seriess.append(series)
        progresslogger.info(f'\t\t\tSeries {series_id} added')
    # Always set/update the source_doi in case it has changed
    series.source_doi = args.source_doi
    series.source_url = args.source_url
    series.excluded = False
    build_instance(client, args, sess, series, instance_id, hash, size, blob_name)
    return


def build_study(client, args, sess, patient, study_id, series_id, instance_id, hash, size, blob_name):
    try:
        study = next(study for study in patient.studies if study.study_instance_uid == study_id)
        progresslogger.info(f'\t\tStudy {study_id} exists')
    except StopIteration:
        study = IDC_Study()
        study.study_instance_uid = study_id
        patient.studies.append(study)
        progresslogger.info(f'\t\tStudy {study_id} added')
    build_series(client, args, sess, study, series_id, instance_id, hash, size, blob_name)
    return


def build_patient(client, args, sess, collection, patient_id, study_id, series_id, instance_id, hash, size, blob_name):
    try:
        patient = next(patient for patient in collection.patients if patient.submitter_case_id == patient_id)
        progresslogger.info(f'\tPatient {patient_id} exists')
    except StopIteration:
        patient = IDC_Patient()
        patient.submitter_case_id = patient_id
        collection.patients.append(patient)
        progresslogger.info(f'\tPatient {patient_id} added')
    build_study(client, args, sess, patient, study_id, series_id, instance_id, hash, size, blob_name)
    return


def build_collection(client, args, sess, collection_id, patient_id, study_id, series_id, instance_id, hash, size, blob_name):
    collection = sess.query(IDC_Collection).filter(IDC_Collection.collection_id == collection_id).first()
    if not collection:
        # The collection is not currently in the DB, so add it
        collection = IDC_Collection()
        collection.collection_id = collection_id
        sess.add(collection)
        progresslogger.info(f'Collection {collection_id} added')
    else:
        progresslogger.info(f'Collection {collection_id} exists')
    build_patient(client, args, sess, collection, patient_id, study_id, series_id, instance_id, hash, size, blob_name)
    return


def prebuild(args):
    client = storage.Client()
    src_bucket = storage.Bucket(client, args.src_bucket)

    sql_uri = f'postgresql+psycopg2://{settings.CLOUD_USERNAME}:{settings.CLOUD_PASSWORD}@{settings.CLOUD_HOST}:{settings.CLOUD_PORT}/{settings.CLOUD_DATABASE}'
    # sql_engine = create_engine(sql_uri, echo=True)
    sql_engine = create_engine(sql_uri)

    with Session(sql_engine) as sess:
        client = storage.Client()
        dones = sess.query(IDC_Series, IDC_Instance.gcs_url).join(IDC_Instance.seriess). \
            filter(IDC_Series.source_doi == args.source_doi).filter(IDC_Instance.idc_version == args.version).all()
        dones = set([row['gcs_url'].replace(f'gs://{args.src_bucket}/', '') for row in dones])
        # dones = set(open(successlogger.handlers[0].baseFilename).read().splitlines())
        # If we have a table of PatientID,StudyInstanceuid,seriesinstanceuid,sopInstanceuid,filepath metadata
        bucket = client.bucket(args.src_bucket)
        data = [row.split(',') for row in open(args.metadata_table).read().splitlines()]
        patients = set(str(row[0]) for row in data)
        patients = list(patients)
        patients.sort()
        print(time.asctime())
        n=0
        for patient in patients:
            studies = [row for row in data if patient == row[0]]
            n += 1
            if n%100 == 0:
                print(n)
        print(time.asctime())
        with open(args.metadata_table) as csvfile:
            reader = csv.DictReader(csvfile, fieldnames=['PatientID', 'StudyInstanceUID', 'SeriesInstanceUID', 'SOPInstanceUID', 'filepath'])
            data = open()
            skip=True
            n=0
            for r in reader:
                if skip:
                    skip = False
                    continue
                patient_id = r['PatientID']
                study_id = r['StudyInstanceUID']
                series_id = r['SeriesInstanceUID']
                instance_id = r['SOPInstanceUID']
                collection_id = args.collection_id

                blob_name = r['filepath'].replace(f'gs://{args.src_bucket}/', '')
                if blob_name in dones:
                    progresslogger.info(f"Skipping {blob_name}")
                    continue
                blob = bucket.blob(blob_name)
                blob.reload()
                try:
                    hash = b64decode(blob.md5_hash).hex()
                except TypeError:
                    # Can't get md5 hash for some blobs (maybe multipart copied/)
                    # So try to compute it
                    try:
                        hash = md5_hasher(f"{args.mount_point}/{blob.name}")
                        progresslogger.info(f'Computed md5 hash of {blob_name}')
                    except Exception as exc:
                        errlogger.error(f'Failed to get hash/sizeof {blob_name}')
                        exit
                size = blob.size
                build_collection(client, args, sess, collection_id, patient_id, study_id, series_id, instance_id, hash,
                             size, blob.name)
                n += 1
                if not n%500:
                    sess.commit()
        sess.commit()
        if args.validate:
            if args.third_party:
                if validate_analysis_result(args) == -1:
                    exit -1
            else:
                if validate_original_collection(args) == -1:
                    exit -1

        if args.gen_hashes:
            gen_hashes(args.collection_id)
        return


if __name__ == '__main__':

    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('--version', default=settings.CURRENT_VERSION)
    parser.add_argument('--src_bucket', default='dac-vhm-dst', help='Bucket containing WSI instances')
    parser.add_argument('--metadata_table', default='./bq-results-20240223-035630-1708660660065.csv', help='csv table of study, series, SOPInstanceUID, filepath')
    parser.add_argument('--mount_point', default='/mnt/disks/idc-etl/visible_human_project', help='Directory on which to mount the bucket.\
                The script will create this directory if necessary.')
    parser.add_argument('--subdir', default='', help="Subdirectory of mount_point at which to start walking directory")
    parser.add_argument('--startswith', default=[], help='Only include files whose name startswith a string in the list. If the list is empty, include all')
    parser.add_argument('--collection_id', default='NLM_visible_human_project', help='idc_webapp_collection id of the collection or ID of analysis result to which instances belong.')
    parser.add_argument('--source_doi', default='', help='Collection DOI')
    parser.add_argument('--source_url', default='https://www.nlm.nih.gov/research/visible/visible_human.html',\
                        help='Info page URL')
    parser.add_argument('--license', default = {"license_url": 'https://www.nlm.nih.gov/databases/download/terms_and_conditions.html',\
            "license_long_name": "National Library of Medicine Terms and Conditions; May 21, 2019", \
            "license_short_name": "National Library of Medicine Terms and Conditions; May 21, 2019"})
    parser.add_argument('--third_party', type=bool, default=False, help='True if from a third party analysis result')
    parser.add_argument('--validate', type=bool, default=True, help='True if validation is to be performed')
    parser.add_argument('--gen_hashes', type=bool, default=True, help='True if hashes are to be generated')

    args = parser.parse_args()
    print("{}".format(args), file=sys.stdout)
    args.client=storage.Client()

    prebuild(args)

