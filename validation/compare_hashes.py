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

# This script compares our hierarchical hashes with those generated by NBIA. This is
# mostly to test NBIA progress.

import sys
import os
import argparse
import hashlib
import logging
from time import sleep
from logging import INFO
from utilities.tcia_helpers import get_hash, get_access_token, get_images_with_md5_hash, get_images_with_md5_hash_nlst,\
    get_TCIA_patients_per_collection, get_TCIA_studies_per_patient, get_TCIA_series_per_study, NBIA_AUTH_URL, \
    get_hash_nlst, NLST_AUTH_URL
from ingestion.utilities.utils import get_merkle_hash

from python_settings import settings
# import settings as etl_settings
from google.cloud import bigquery

# settings.configure(etl_settings)
assert settings.configured
import psycopg2
from psycopg2.extras import DictCursor
import zipfile
import io
import pydicom

from idc.models import Base, Version, Collection
from sqlalchemy.orm import Session


from python_settings import settings

from sqlalchemy import create_engine
from sqlalchemy_utils import register_composites


# Get a list of instance md5 hashes from NBIA
def get_instance_hashes(series_instance_uid, collection_id, access_token):
    if collection_id == 'NLST':
        zip_file = io.BytesIO(get_images_with_md5_hash_nlst(series_instance_uid).content)
    else:
        zip_file = io.BytesIO(get_images_with_md5_hash(series_instance_uid).content)
    zipfile_obj = zipfile.ZipFile(zip_file)
    try:
        md5_hashes = [row.decode().split(',')  for row in zipfile_obj.open("md5hashes.csv").read().splitlines()[1:]]
    except KeyError as exc:
        print(exc)
        return

    for instance in md5_hashes:
        with zipfile_obj.open(instance[0]) as dcm_obj:
            instance.append(pydicom.dcmread(dcm_obj, stop_before_pixels=True).SOPInstanceUID)

    return (md5_hashes, zipfile_obj)

def compare_instance_hashes(access_token, refresh_token, cur, args, collection, patient, study, series):
    client = bigquery.Client()
    # access_token = get_access_token(auth_server = NBIA_AUTH_URL)

    query = f"""
        SELECT sop_instance_uid, instance_hash, series_instances
        FROM `idc-dev-etl.idc_v2.series` as se
        JOIN `idc-dev-etl.idc_v2.instance` as i
        ON se.id = i.series_id
        WHERE se.idc_version_number=2 AND se.series_instance_uid ='{series.series_instance_uid}'
      """

    # cur.execute(query)
    idc_instances = [{'sop_instance_uid':row['sop_instance_uid'], 'instance_hash':row['instance_hash']} for row in client.query(query)]
    # idc_instances = cur.fetchall()
    # access_token = get_access_token(auth_server = NBIA_AUTH_URL)

    nbia_instances, zipfile_obj = get_instance_hashes(series.series_instance_uid, collection.collection_id, access_token)


    if len(nbia_instances) != len(idc_instances):
        # print('                %-32s Differing instance count for series %s: IDC: %s, NBIA: %s; %s' %  (series_instance_uid,
        #                 len(idc_instances), len(nbia_instances)))
        print('            %-32s Differing instance count for series: IDC: %s, NBIA: %s' %  (series.series_instance_uid,
                        len(idc_instances), len(nbia_instances)))
        rootlogger.info('            %-32s Differing instance count for series: IDC: %s, NBIA: %s', series.series_instance_uid,
                        len(idc_instances), len(nbia_instances))
    else:
        for idc_instance in idc_instances:
            nbia_instance = next(nbia_instance for nbia_instance in nbia_instances if nbia_instance[2]==idc_instance['sop_instance_uid'])
            md5 = hashlib.md5()
            md5.update(zipfile_obj.open(nbia_instance[0]).read())
            pyhash = md5.hexdigest()
            idc_hash = idc_instance['instance_hash']
            nbia_hash = nbia_instance[1]
            if pyhash != idc_hash:
                print('                %-32s IDC: %s, py: %s, NBIA: %s; IDC/NBIA mismatch: %s' % ( idc_instance['sop_instance_uid'], idc_instance['instance_hash'],
                                pyhash, nbia_instance[1], idc_hash == nbia_hash))
                rootlogger.info('                %-32s IDC: %s, py: %s. NBIA: %s; IDC/NBIA mismatch: %s', idc_instance['sop_instance_uid'], idc_instance['instance_hash'],
                                pyhash, nbia_instance[1], idc_hash == nbia_hash)

            else:
                print('                %-32s IDC: %s, NBIA: %s; %s' % ( idc_instance['sop_instance_uid'], idc_instance['instance_hash'],
                                nbia_instance[1], idc_hash == nbia_hash))
                rootlogger.info('                %-32s IDC: %s, NBIA: %s; %s', idc_instance['sop_instance_uid'], idc_instance['instance_hash'],
                                nbia_instance[1], idc_hash == nbia_hash)


def compare_series_hashes(access_token, refresh_token, cur, args, collection, patient, study):
    query = f"""
        SELECT series_instance_uid, series_hash, series_instances
        FROM study{args.suffix} as st
        JOIN series{args.suffix} as se
        ON st.id = se.study_id
        WHERE st.idc_version_number=2 AND st.study_instance_uid ='{study.study_instance_uid}'
      """

    cur.execute(query)
    series = cur.fetchall()
    # access_token = get_access_token(auth_server=NBIA_AUTH_URL)

    tcia_series = get_TCIA_series_per_study(collection.collection_id, patient.submitter_case_id, study.study_instance_uid)

    tcia_series = sorted(tcia_series, key=lambda id: id['SeriesInstanceUID'])
    for series in tcia_series:
        if not series['SeriesInstanceUID'] in [serie[0] for serie in series]:
            print('        {:32} Series {} not in IDC'.format(study.study_instance_uid, series['SeriesInstanceUID']))
        else:
            row = [s for s in series if s[0] == series['SeriesInstanceUID']][0]
    # if len(series) == len(tcia_series):
    #     for row in series:
            # access_token = get_access_token(auth_server=NBIA_AUTH_URL)
            try:
                if collection.collection_id == 'NLST':
                    result, access_token, refresh_token = \
                        get_hash_nlst({'SeriesInstanceUID': row[0]}, access_token=access_token, refresh_token=refresh_token)
                else:
                    result, access_token, refresh_token = \
                        get_hash({'SeriesInstanceUID': row[0]}, access_token=access_token, refresh_token=refresh_token)

                if result.status_code == 504:
                    print('            {:32} IDC: {}, error: {}, reason: {}'.format(row[0], row[1], result.status_code,
                                                                              result.reason))
                    rootlogger.info('            %-32s IDC: %s, error: %s, reason: %s', row[0], row[1], result.status_code,
                                    result.reason)

                nbia_hash = result.text
                idc_hash = row[1]
                if 'series' in args.log_level:
                    print('            {:32} IDC: {}, NBIA: {}; {}'.format(row[0], row[1], nbia_hash, idc_hash==nbia_hash))
                    rootlogger.info('            %-32s IDC: %s, NBIA: %s; %s', row[0], row[1], nbia_hash, idc_hash==nbia_hash)
                if not args.stop_expansion == 'series':
                    if idc_hash != nbia_hash or args.expand_all:
                        if args.stop and (nbia_hash == 'd41d8cd98f00b204e9800998ecf8427e' or nbia_hash == ""):
                            if 'series' in args.log_level:
                                print('        {:32} Skip expansion'.format(""))
                                rootlogger.info('        %-32s Skip expansion', "")
                        else:
                            compare_instance_hashes(access_token, refresh_token, cur, args, collection, patient, study, series)

            except TimeoutError as esc:
                print('{:32} IDC: {}, error: {}, reason: {}'.format(row[0], row[1], result.status_code, result.reason))
                rootlogger.info('%-32s IDC: %s, error: %s, reason: %s', row[0], row[1], result.status_code, result.reason)
    else:
        print('        {:32} Different number of series: IDC: {}, NBIA: {}'.format(study.study_instance_uid,
                len(series), len(tcia_series)))



def compare_study_hashes(access_token, refresh_token, sess, args, collection, patient):
    studies = [patient.studies]

    studies = get_TCIA_studies_per_patient(collection.collection_id, patient.submitter_case_id)

    # if len(studies) == len(tcia_studies):
    studies = sorted(studies, key=lambda id: id['StudyInstanceUID'])
    for study in studies:
        try:
            if collection.collection_id == 'NLST':
               result, access_token, refresh_token = get_hash_nlst({'StudyInstanceUID': study.study_instance_uid},
                        access_token=access_token, refresh_token=refresh_token)
            else:
                result, access_token, refresh_token = get_hash({'StudyInstanceUID': study.study_instance_uid},
                        access_token=access_token, refresh_token=refresh_token)
            if result.status_code == 504:
                print('        {:32} IDC: {}, error: {}, reason: {}'.format(patient.submitter_uid, study.study_instance_uid, result.status_code,
                                                                        result.reason))
                rootlogger.info('        %-32s IDC: %s, error: %s, reason: %s', patient.submitter_uid, study.study_instance_uid, result.status_code,
                                result.reason)

            nbia_hash = result.text
            idc_hash = study.hashes.tcia
            if 'study' in args.log_level:
                print('        {:32} IDC: {}, NBIA: {}; {}'.format(patient.submitter_uid, study.study_instance_uid, nbia_hash, idc_hash==nbia_hash))
                rootlogger.info('        %-32s IDC: %s, NBIA: %s; %s', patient.submitter_uid, study.study_instance_uid, nbia_hash, idc_hash==nbia_hash)
            if not args.stop_expansion == 'study':
                if idc_hash != nbia_hash or args.expand_all:
                    if args.stop and (nbia_hash == 'd41d8cd98f00b204e9800998ecf8427e' or nbia_hash == ""):
                        if 'study' in args.log_level:
                            print('        {:32} Skip expansion'.format(""))
                            rootlogger.info('        %-32s Skip expansion', "")
                    else:
                        compare_series_hashes(access_token, refresh_token, sess, args, collection, patient, study)
        except TimeoutError as esc:
            print('{:32} IDC: {}, error: {}, reason: {}'.format(patient.submitter_uid, study.study_instance_uid, result.status_code, result.reason))
            rootlogger.info('%-32s IDC: %s, error: %s, reason: %s', patient.submitter_uid, study.study_instance_uid, result.status_code, result.reason)
    # else:
    #     print('    {:32} Different number of studies: IDC: {}, NBIA: {}'.format(submitter_case_id,
    #             len(studies), len(tcia_studies)))

def validate_idc_collection_hash(collection):
    idc_patient_hashes = [patient.hashes.tcia for patient in collection.patients]
    idc_collection_hash = get_merkle_hash(idc_patient_hashes)
    if idc_collection_hash != collection.hashes.tcia:
        print('idc collection hash hierarchically incorrect')
    else:
        print ('idc collection hash hierarchically correct')

def compare_patient_hashes(access_token, refresh_token, sess, args, collection):
    patients = collection.patients
    # validate_idc_collection_hash(collection)
#    access_token = get_access_token(auth_server=NBIA_AUTH_URL)
    tcia_patients = get_TCIA_patients_per_collection(collection.collection_id)
    if not set([patient.submitter_case_id for patient in patients]) == set([patient['PatientId'] for patient in tcia_patients]):
        errlogger.info("    Patients are different")
        return
    for patient in patients:
        try:
            if collection.collection_id == 'NLST':
                result = get_hash_nlst(
                {'Collection': collection.collection_id, 'PatientID': patient.submitter_case_id}, access_token=access_token)
            else:
                result = get_hash(
                {'Collection': collection.collection_id, 'PatientID': patient.submitter_case_id}, access_token=access_token)
            if result.status_code == 504:
                print('    {:32} error: {}, reason: {}'.format(patient.submitter_case_id, result.status_code,
                                                                      result.reason))
                rootlogger.info('    %-32s error: %s, reason: %s', patient.submitter_case_id, result.status_code,
                                result.reason)

            nbia_hash = result.text
            idc_hash = patient.hashes.tcia
            if 'patient' in args.log_level:
                print('    {:32} IDC: {}, NBIA: {}; {}'.format(patient.submitter_case_id, idc_hash, nbia_hash, idc_hash==nbia_hash))
                rootlogger.info('    %-32s IDC: %s, NBIA: %s; %s', patient.submitter_case_id, idc_hash, nbia_hash, idc_hash==nbia_hash)
            if not args.stop_expansion == 'patient':
                if idc_hash != nbia_hash or args.expand_all:
                    # if args.stop and (nbia_hash == 'd41d8cd98f00b204e9800998ecf8427e' or nbia_hash == ""):
                    if args.stop:
                        if 'patient' in args.log_level:
                            print('    {:32} Skip expansion'.format(""))
                            rootlogger.info('    %-32s Skip expansion', "")
                    else:
                        compare_study_hashes(access_token, refresh_token, sess, args, collection, patient)
        except TimeoutError as esc:
            print('{:32} error: {}, reason: {}'.format(patient.submitter_case_id, result.status_code, result.reason))
            rootlogger.info('%-32s error: %s, reason: %s', patient.submitter_case_id, result.status_code, result.reason)
    # else:
    #     print('{:32} Different number of patients: IDC: {}, NBIA: {}'.format(tcia_api_collection_id,
    #         len(patients), len(tcia_patients)))

def compare_collection_hashes(sess, args):
    query = f"""
        SELECT tcia_api_collection_id, collection_hash
        FROM collection{args.suffix}
        WHERE idc_version_number={args.version}
        ORDER BY tcia_api_collection_id
      """
    version = sess.query(Version).filter(Version.version == args.version).first()
    collections = version.collections
    collections = sorted(version.collections, key=lambda collection: collection.collection_id)

    skips = open(args.skips).read().splitlines()

    access_token, refresh_token = get_access_token(auth_server=NBIA_AUTH_URL)
    if args.collections != []:
        collections = [collection for collection in collections if collection.collection_id in args.collections]
        if collections[0].collection_id == 'NLST':
            access_token, refresh_token = get_access_token(auth_server=NLST_AUTH_URL)


    for collection in collections:
        # access_token = get_access_token(auth_server=NBIA_AUTH_URL)
        collection_id = collection.collection_id
        if collection_id not in skips:
            try:
                if collection_id == 'APOLLO':
                    result, access_token, refresh_token = get_hash({'Collection': 'APOLLO-5-LSCC'}, access_token=access_token, refresh_token=refresh_token)
                else:
                    # result, access_token, refresh_token = get_hash({'Collection': collection_id},
                    #                                                access_token=access_token,
                    #                                                refresh_token=refresh_token)
                    if collection_id == 'NLST':
                        result = get_hash_nlst({'Collection': collection_id}, access_token=access_token)
                    else:
                        result = get_hash({'Collection': collection_id}, access_token=access_token)

                if result.status_code == 504:
                    print('{:32} IDC: {}, error: {}, reason: {}'.format(collection_id, collection.hashes.tcia, result.status_code, result.reason))
                    rootlogger.info('%-32s IDC: %s, error: %s, reason: %s', collection_id, collection.hashes.tcia, result.status_code, result.reason)
                # if not result.status_code == 200:
                #     print('{:32} IDC: {}, error: {}, reason: {}'.format(collection_id, row[1], result.status_code, result.reason))
                #     rootlogger.info('%-32s IDC: %s, error: %s, reason: %s', collection_id, row[1], result.status_code, result.reason)
                #     break

                nbia_hash = result.text
                idc_hash = collection.hashes.tcia
                if 'collection' in args.log_level:
                    print('{:32} IDC: {}, NBIA: {}; {}'.format(collection_id, collection.hashes.tcia, nbia_hash, idc_hash==nbia_hash))
                    if idc_hash==nbia_hash:
                        rootlogger.info('%-32s IDC: %s, NBIA: %s; %s', collection_id, collection.hashes.tcia, nbia_hash, idc_hash==nbia_hash)
                    else:
                        errlogger.info('%-32s IDC: %s, NBIA: %s; %s', collection_id, collection.hashes.tcia, nbia_hash, idc_hash==nbia_hash)
                if not args.stop_expansion == 'collection':
                    if idc_hash != nbia_hash or args.expand_all:
                        if args.stop and (nbia_hash == 'd41d8cd98f00b204e9800998ecf8427e' or nbia_hash == ""):
                            if 'collection' in args.log_level:
                                print('{:32} Skip expansion'.format(""))
                                rootlogger.info('%-32s Skip expansion', "")
                        else:
                            compare_patient_hashes(access_token, refresh_token, sess, args, collection)
            except TimeoutError as esc:
                print('{:32} IDC: {}, error: {}, reason: {}'.format(collection_id, collection.hashes.tcia, result.status_code, result.reason))
                rootlogger.info('%-32s IDC: %s, error: %s, reason: %s', collection_id, collection.hashes.tcia, result.status_code, result.reason)
                # sleep(retries*120)
        else:
            rootlogger.info('Skipping %-32s ', collection_id)

# def compare_hashes(args):
#     conn = psycopg2.connect(dbname=args.db, user=settings.LOCAL_USERNAME,
#                             password=settings.LOCAL_PASSWORD, host=settings.LOCAL_HOST)
#     with conn:
#         with conn.cursor(cursor_factory=DictCursor) as cur:
#             compare_collection_hashes(cur, args)
#             pass


def compare_hashes(args):
    sql_uri = f'postgresql+psycopg2://{settings.CLOUD_USERNAME}:{settings.CLOUD_PASSWORD}@{settings.CLOUD_HOST}:{settings.CLOUD_PORT}/{args.db}'
    # sql_engine = create_engine(sql_uri, echo=True) # Use this to see the SQL being sent to PSQL
    sql_engine = create_engine(sql_uri)
    args.sql_uri = sql_uri # The subprocesses need this uri to create their own SQL engine

    # Create the tables if they do not already exist
    # Base.metadata.create_all(sql_engine)

    # Enable the underlying psycopg2 to deal with composites
    conn = sql_engine.connect()
    register_composites(conn)

    with Session(sql_engine) as sess:
        compare_collection_hashes(sess, args)
        pass



if __name__ == '__main__':
    rootlogger = logging.getLogger('root')
    root_fh = logging.FileHandler('{}/logs/compare_hashes_log.log'.format(os.environ['PWD']))
    # rootformatter = logging.Formatter('%(levelname)s:root:%(message)s')
    rootformatter = logging.Formatter('%(message)s')
    rootlogger.addHandler(root_fh)
    root_fh.setFormatter(rootformatter)
    rootlogger.setLevel(INFO)

    errlogger = logging.getLogger('root.err')
    err_fh = logging.FileHandler('{}/logs/compare_hashes_err.log'.format(os.environ['PWD']))
    errformatter = logging.Formatter('%(levelname)s:err:%(message)s')
    errlogger.addHandler(err_fh)
    err_fh.setFormatter(errformatter)

    version = 10
    parser = argparse.ArgumentParser()
    # parser.add_argument('--db', default=f'idc_v{version}', help='Database to compare against')
    parser.add_argument('--db', default=f'idc_v{version}', help='Database to compare against')
    parser.add_argument('--suffix', default="")
    parser.add_argument('--stop_expansion', default="Collection", help="Level at which to stop expansion")
    parser.add_argument('--stop', default=False, help='Stop expansion if no hash returned by NBIA')
    parser.add_argument('--expand_all', default=False, help="Expand regardless of whether hashes match.")
    parser.add_argument('--log_level', default=("collection, patient, study, series, instance"),
                        help='Levels at which to log')
    parser.add_argument('--collections', default=['ISPY2'], \
        help='List of collections to compare. If empty, compare all collections')
    parser.add_argument('--skips', default='./logs/compare_hashes_skips')

    args = parser.parse_args()
    args.version = version


    print("{}".format(args), file=sys.stdout)

    compare_hashes(args)
