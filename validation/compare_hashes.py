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
from utilities.tcia_helpers import get_hash, get_access_token, get_images_with_md5_hash

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

# Get a list of instance md5 hashes from NBIA
def get_instance_hashes(series_instance_uid):
    zip_file = io.BytesIO(get_images_with_md5_hash(series_instance_uid).content)
    zipfile_obj = zipfile.ZipFile(zip_file)
    md5_hashes = [row.decode().split(',')  for row in zipfile_obj.open("md5hashes.csv").read().splitlines()[1:]]

    for instance in md5_hashes:
        with zipfile_obj.open(instance[0]) as dcm_obj:
            instance.append(pydicom.dcmread(dcm_obj, stop_before_pixels=True).SOPInstanceUID)

    return (md5_hashes, zipfile_obj)

def compare_instance_hashes(access_token, cur, args, series_instance_uid):
    client = bigquery.Client()

    query = f"""
        SELECT sop_instance_uid, instance_hash, series_instances
        FROM `idc-dev-etl.idc_v2.series` as se
        JOIN `idc-dev-etl.idc_v2.instance` as i
        ON se.id = i.series_id
        WHERE se.idc_version_number=2 AND se.series_instance_uid ='{series_instance_uid}'
      """

    # cur.execute(query)
    idc_instances = [{'sop_instance_uid':row['sop_instance_uid'], 'instance_hash':row['instance_hash']} for row in client.query(query)]
    # idc_instances = cur.fetchall()
    # access_token = get_access_token(url = "https://public-dev.cancerimagingarchive.net/nbia-api/oauth/token")['access_token']

    nbia_instances, zipfile_obj = get_instance_hashes(series_instance_uid)

    if len(nbia_instances) != len(idc_instances):
        print('\t\t\t\t%-32s Differing instance count for series %s: IDC: %s, NBIA: %s; %s' %  (series_instance_uid,
                        len(idc_instances), len(nbia_instances)))
        rootlogger.info('\t\t\t\t%-32s Differing instance count for series %s: IDC: %s, NBIA: %s; %s', series_instance_uid,
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
                print('\t\t\t\t%-32s IDC: %s, py: %s, NBIA: %s; %s; IDC/pyhash mismatch' % ( idc_instance['sop_instance_uid'], idc_instance['instance_hash'],
                                pyhash, nbia_instance[1], idc_hash == nbia_hash))
                rootlogger.info('\t\t\t\t%-32s IDC: %s, py: %s. NBIA: %s; %s; IDC/pyhash mismatch', idc_instance['sop_instance_uid'], idc_instance['instance_hash'],
                                pyhash, nbia_instance[1], idc_hash == nbia_hash)

            else:
                print('\t\t\t\t%-32s IDC: %s, NBIA: %s; %s' % ( idc_instance['sop_instance_uid'], idc_instance['instance_hash'],
                                nbia_instance[1], idc_hash == nbia_hash))
                rootlogger.info('\t\t\t\t%-32s IDC: %s, NBIA: %s; %s', idc_instance['sop_instance_uid'], idc_instance['instance_hash'],
                                nbia_instance[1], idc_hash == nbia_hash)


def compare_series_hashes(access_token, cur, args, study_instance_uid):
    query = f"""
        SELECT series_instance_uid, series_hash, series_instances
        FROM study{args.suffix} as st
        JOIN series{args.suffix} as se
        ON st.id = se.study_id
        WHERE st.idc_version_number=2 AND st.study_instance_uid ='{study_instance_uid}'
      """

    cur.execute(query)
    series = cur.fetchall()
    # access_token = get_access_token(url = "https://public-dev.cancerimagingarchive.net/nbia-api/oauth/token")['access_token']

    for row in series:
        try:
            result = get_hash({'SeriesInstanceUID': row[0]}, access_token=access_token)
            if not result.status_code == 200:
                print('\t\t\t{:32} IDC: {}, error: {}, reason: {}'.format(row[0], row[1], result.status_code, result.reason))
                rootlogger.info('\t\t\t%-32s IDC: %s, error: %s, reason: %s', row[0], row[1], result.status_code, result.reason)
            else:
                nbia_hash = result.text
                idc_hash = row[1]
                if 'series' in args.log_level:
                    print('\t\t\t{:32} IDC: {}, NBIA: {}; {}'.format(row[0], row[1], nbia_hash, idc_hash==nbia_hash))
                    rootlogger.info('\t\t\t%-32s IDC: %s, NBIA: %s; %s', row[0], row[1], nbia_hash, idc_hash==nbia_hash)
                if not args.stop_expansion == 'series':
                    if idc_hash != nbia_hash or args.expand_all:
                        if args.stop and (nbia_hash == 'd41d8cd98f00b204e9800998ecf8427e' or nbia_hash == ""):
                            if 'series' in args.log_level:
                                print('\t\t{:32} Skip expansion'.format(""))
                                rootlogger.info('\t\t%-32s Skip expansion', "")
                        else:
                            compare_instance_hashes(access_token, cur, args, row[0])

        except TimeoutError as esc:
            print('{:32} IDC: {}, error: {}, reason: {}'.format(row[0], row[1], result.status_code, result.reason))
            rootlogger.info('%-32s IDC: %s, error: %s, reason: %s', row[0], row[1], result.status_code, result.reason)


def compare_study_hashes(access_token, cur, args, tcia_api_collection_id, submitter_case_id):
    query = f"""
        SELECT study_instance_uid, study_hash
        FROM collection{args.suffix} as c 
        JOIN patient{args.suffix} as p 
        ON c.id = p.collection_id
        JOIN study{args.suffix} as st
        ON p.id = st.patient_id
        WHERE p.idc_version_number=2 AND c.tcia_api_collection_id = '{tcia_api_collection_id}' AND p.submitter_case_id ='{submitter_case_id}'
      """

    cur.execute(query)
    studies = cur.fetchall()
    # access_token = get_access_token(url = "https://public-dev.cancerimagingarchive.net/nbia-api/oauth/token")['access_token']

    for row in studies:
        try:
            result = get_hash({'StudyInstanceUID': row[0]}, access_token=access_token)
            if not result.status_code == 200:
                print('\t\t{:32} IDC: {}, error: {}, reason: {}'.format(row[0], row[1], result.status_code, result.reason))
                rootlogger.info('\t\t%-32s IDC: %s, error: %s, reason: %s', row[0], row[1], result.status_code, result.reason)
            else:
                nbia_hash = result.text
                idc_hash = row[1]
                if 'study' in args.log_level:
                    print('\t\t{:32} IDC: {}, NBIA: {}; {}'.format(row[0], row[1], nbia_hash, idc_hash==nbia_hash))
                    rootlogger.info('\t\t%-32s IDC: %s, NBIA: %s; %s', row[0], row[1], nbia_hash, idc_hash==nbia_hash)
                if not args.stop_expansion == 'study':
                    if idc_hash != nbia_hash or args.expand_all:
                        if args.stop and (nbia_hash == 'd41d8cd98f00b204e9800998ecf8427e' or nbia_hash == ""):
                            if 'study' in args.log_level:
                                print('\t\t{:32} Skip expansion'.format(""))
                                rootlogger.info('\t\t%-32s Skip expansion', "")
                        else:
                            compare_series_hashes(access_token, cur, args, row[0])
        except TimeoutError as esc:
            print('{:32} IDC: {}, error: {}, reason: {}'.format(row[0], row[1], result.status_code, result.reason))
            rootlogger.info('%-32s IDC: %s, error: %s, reason: %s', row[0], row[1], result.status_code, result.reason)

def compare_patient_hashes(access_token, cur, args, tcia_api_collection_id):
    query = f"""
        SELECT submitter_case_id, patient_hash
        FROM collection{args.suffix} as c 
        JOIN patient{args.suffix} as p 
        ON c.id = p.collection_id
        WHERE p.idc_version_number=2 AND c.tcia_api_collection_id = '{tcia_api_collection_id}'
      """

    cur.execute(query)
    patients = cur.fetchall()
    # access_token = get_access_token(url = "https://public-dev.cancerimagingarchive.net/nbia-api/oauth/token")['access_token']
    access_token = get_access_token(auth_server = "https://public-dev.cancerimagingarchive.net/nbia-api/oauth/token")

    for row in patients:
        try:
            result = get_hash({'Collection': tcia_api_collection_id, 'PatientID': row[0]}, access_token=access_token)
            if not result.status_code == 200:
                print('\t{:32} IDC: {}, error: {}, reason: {}'.format(row[0], row[1], result.status_code, result.reason))
                rootlogger.info('\t%-32s IDC: %s, error: %s, reason: %s', row[0], row[1], result.status_code, result.reason)
            else:
                nbia_hash = result.text
                idc_hash = row[1]
                if 'patient' in args.log_level:
                    print('\t{:32} IDC: {}, NBIA: {}; {}'.format(row[0], row[1], nbia_hash, idc_hash==nbia_hash))
                    rootlogger.info('\t%-32s IDC: %s, NBIA: %s; %s', row[0], row[1], nbia_hash, idc_hash==nbia_hash)
                if not args.stop_expansion == 'patient':
                    if idc_hash != nbia_hash or args.expand_all:
                        if args.stop and (nbia_hash == 'd41d8cd98f00b204e9800998ecf8427e' or nbia_hash == ""):
                            if 'patient' in args.log_level:
                                print('\t{:32} Skip expansion'.format(""))
                                rootlogger.info('\t%-32s Skip expansion', "")
                        else:
                            compare_study_hashes(access_token, cur, args, tcia_api_collection_id, row[0])
        except TimeoutError as esc:
            print('{:32} IDC: {}, error: {}, reason: {}'.format(row[0], row[1], result.status_code, result.reason))
            rootlogger.info('%-32s IDC: %s, error: %s, reason: %s', row[0], row[1], result.status_code, result.reason)


def compare_collection_hashes(cur, args):
    query = f"""
        SELECT tcia_api_collection_id, collection_hash
        FROM collection{args.suffix}
        WHERE idc_version_number=2
        ORDER BY tcia_api_collection_id
      """

    cur.execute(query)
    collections = cur.fetchall()
    access_token = get_access_token(auth_server = "https://public-dev.cancerimagingarchive.net/nbia-api/oauth/token")

    skips = open(args.skips).read().splitlines()

    if args.collections != []:
        collections = [collection for collection in collections if collection[0] in args.collections]

    for row in collections:
        collection_id = row[0]
        if collection_id not in skips:
            retries = 0
            for retries in range(1):
                try:

                    result = get_hash({'Collection': collection_id}, access_token=access_token)
                    if not result.status_code == 200:
                        print('{:32} IDC: {}, error: {}, reason: {}'.format(collection_id, row[1], result.status_code, result.reason))
                        rootlogger.info('%-32s IDC: %s, error: %s, reason: %s', collection_id, row[1], result.status_code, result.reason)
                        # sleep((retries+1)*120)
                        continue
                    else:
                        nbia_hash = result.text
                        idc_hash = row[1]
                        if 'collection' in args.log_level:
                            print('{:32} IDC: {}, NBIA: {}; {}'.format(collection_id, row[1], nbia_hash, idc_hash==nbia_hash))
                            rootlogger.info('%-32s IDC: %s, NBIA: %s; %s', collection_id, row[1], nbia_hash, idc_hash==nbia_hash)
                        if not args.stop_expansion == 'collection':
                            if idc_hash != nbia_hash or args.expand_all:
                                if args.stop and (nbia_hash == 'd41d8cd98f00b204e9800998ecf8427e' or nbia_hash == ""):
                                    if 'collection' in args.log_level:
                                        print('{:32} Skip expansion'.format(""))
                                        rootlogger.info('%-32s Skip expansion', "")
                                else:
                                    compare_patient_hashes(access_token, cur, args, collection_id)
                    break
                except TimeoutError as esc:
                    print('{:32} IDC: {}, error: {}, reason: {}'.format(collection_id, row[1], result.status_code, result.reason))
                    rootlogger.info('%-32s IDC: %s, error: %s, reason: %s', collection_id, row[1], result.status_code, result.reason)
                    sleep(retries*120)

def compare_hashes(args):
    conn = psycopg2.connect(dbname=args.db, user=settings.DATABASE_USERNAME,
                            password=settings.DATABASE_PASSWORD, host=settings.DATABASE_HOST)
    with conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            compare_collection_hashes(cur, args)
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

    parser = argparse.ArgumentParser()
    parser.add_argument('--db', default='idc', help='Database to compare against')
    parser.add_argument('--suffix', default="")
    parser.add_argument('--stop_expansion', default="", help="Level at which to stop expansion")
    parser.add_argument('--stop', default=False, help='Stop expansion if no hash returned by NBIA')
    parser.add_argument('--expand_all', default=False)
    parser.add_argument('--log_level', default=("collection, patient, study, series, instance"))
    parser.add_argument('--collections', default=['AAPM-RT-MAC'])
    parser.add_argument('--skips', default='./logs/compare_hashes_skips')
    args = parser.parse_args()

    print("{}".format(args), file=sys.stdout)

    compare_hashes(args)
