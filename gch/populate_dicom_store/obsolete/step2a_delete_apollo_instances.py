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
#### This is the mp version of the second step in populating a DICOM store ####
# Because the buckets contain multiple versions of some instances, and a DICOM
# store can hold only one version, it is indeterminant which version is imported.
# Therefore, after importing the buckets, we first delete any instance that has
# more than one version. We also delete any instance that has a final version
# (final_idc_version != 0). This latter is to ensure that there are not retired instances
# that are no longer in the current IDC version.

import argparse
from utilities.logging_config import successlogger, progresslogger, errlogger
from time import sleep

import google
from google.cloud import storage, bigquery
from google.auth.transport import requests
import settings
from multiprocessing import  Process, Queue

def instance_exists(args, dicomweb_sess, study_instance_uid, series_instance_uid, sop_instance_uid):
    # URL to the Cloud Healthcare API endpoint and version
    base_url = "https://healthcare.googleapis.com/v1"
    url = "{}/projects/{}/locations/{}".format(base_url, settings.PUB_PROJECT, settings.GCH_REGION)
    dicomweb_path = "{}/datasets/{}/dicomStores/{}/dicomWeb/studies/{}/series/{}/instances?SOPInstanceUID={}".format(
        url, settings.GCH_DATASET, settings.GCH_DICOMSTORE, study_instance_uid, series_instance_uid, sop_instance_uid
    )
    # Set the required application/dicom+json; charset=utf-8 header on the request
    headers = {"Content-Type": "application/dicom+json; charset=utf-8"}

    delay = 0
    while True:
        response = dicomweb_sess.get(dicomweb_path, headers=headers)
        if response.status_code == 200:
            progresslogger.info(f'p{args.id}: {sop_instance_uid} found')
            # print('%s found',sop_instance_uid)
            return True
        else:
            if response.status_code == 429:
                progresslogger.error(f'p{args.id}: Quota exceeded, delay: {delay+1}')
                delay += 1
                sleep(delay)
            else:
                errlogger.error(f'p{args.id}: Exist testing {sop_instance_uid} {response.status_code}, {response.text}')
                return False


def delete_instance(args, dicomweb_session, study_instance_uid, series_instance_uid, sop_instance_uid):
    # URL to the Cloud Healthcare API endpoint and version
    base_url = "https://healthcare.googleapis.com/v1"
    url = "{}/projects/{}/locations/{}".format(base_url, settings.PUB_PROJECT, settings.GCH_REGION)
    dicomweb_path = "{}/datasets/{}/dicomStores/{}/dicomWeb/studies/{}/series/{}/instances/{}".format(
        url, settings.GCH_DATASET, settings.GCH_DICOMSTORE, study_instance_uid, series_instance_uid, sop_instance_uid
    )
    # Set the required application/dicom+json; charset=utf-8 header on the request
    headers = {"Content-Type": "application/dicom+json; charset=utf-8"}

    delay = 0
    while True:
        response = dicomweb_session.delete(dicomweb_path, headers=headers)
        if response.status_code == 200:
            return True
        else:
            if response.status_code == 429:
                progresslogger.error(f'p{args.id}: Quota exceeded, delay: {delay + 1}')
                delay += 1
                sleep(delay)
            else:
                errlogger.error(f'p{args.id}: Deleteing {sop_instance_uid} {response.status_code}, {response.text}')
                return False


def worker(input, args):
    scoped_credentials, project = google.auth.default(
        ["https://www.googleapis.com/auth/cloud-platform"]
    )
    # Create a DICOMweb requests Session object with the credentials.
    dicomweb_sess = requests.AuthorizedSession(scoped_credentials)

    try:
        # Get the previously copied blobs
        done_instances = set(open(successlogger.handlers[0].baseFilename).read().splitlines())
    except:
        done_instances = set()

    # client = storage.Client()
    for rev_uids, n in iter(input.get, 'STOP'):
        for row in rev_uids:
            if not row['sop_instance_uid'] in done_instances:
                # instance_exists(args, dicomweb_sess, row['study_instance_uid'],
                #                    row['series_instance_uid'], row['sop_instance_uid'])
                if instance_exists(args, dicomweb_sess, row['study_instance_uid'],
                                   row['series_instance_uid'], row['sop_instance_uid']):
                    if delete_instance(args, dicomweb_sess, row['study_instance_uid'],
                                    row['series_instance_uid'], row['sop_instance_uid']):
                        successlogger.info(row['sop_instance_uid'])
                        progresslogger.info(f"p{args.id}: {n}: Instance {row['sop_instance_uid']}  deleted")
                    else:
                        if instance_exists(args, dicomweb_sess, row['study_instance_uid'],
                                           row['series_instance_uid'], row['sop_instance_uid']):
                            errlogger.error(f"p{args.id}: {n}: Instance {row['sop_instance_uid']}  NOT deleted")
                        else:
                            # print(f"{n}: Instance {row['sop_instance_uid']}  deleted")
                            successlogger.info(row['sop_instance_uid'])
                            progresslogger.info(f"p{args.id}: {n}: Instance {row['sop_instance_uid']}  deleted")
                else:
                    errlogger.error(f"p{args.id}: {n}: Instance {row['sop_instance_uid']} not in DICOM store")
            else:
                progresslogger.info(f"p{args.id}: {n}: Instance {row['sop_instance_uid']} previously deleted")
            n += 1

def delete_instances(args):
    client = bigquery.Client()
    try:
        # Get the previously copied blobs
        done_instances = set(open(successlogger.handlers[0].baseFilename).read().splitlines())
    except:
        done_instances = set()


    num_processes = args.processes
    processes = []
    task_queue = Queue()
    # Start worker processes
    for process in range(num_processes):
        args.id = process + 1
        processes.append(
            Process(group=None, target=worker, args=(task_queue, args)))
        processes[-1].start()

    # We first try to delete any instance for which there are multiple versions from public data
    # or are fully retired instances for which there is a single version
    query = f"""
    SELECT DISTINCT study_instance_uid, series_instance_uid, sop_instance_uid
    FROM `{settings.DEV_PROJECT}.{settings.BQ_DEV_INT_DATASET}.all_joined` aj
    JOIN `{settings.DEV_PROJECT}.{settings.BQ_DEV_INT_DATASET}.all_collections` ac ON aj.collection_id=ac.tcia_api_collection_id
    WHERE 
        collection_id like 'APOLLO%'
    AND
        (i_final_idc_version = 0 AND i_init_idc_version=i_rev_idc_version)
    AND 
        ((aj.i_source='tcia' AND ac.tcia_access='Public') 
        OR 
        (aj.i_source='idc' AND ac.idc_access='Public'))
    ORDER BY study_instance_uid, series_instance_uid, sop_instance_uid

    """

    result = client.query(query).result()
    rev_uids = [{'study_instance_uid': row.study_instance_uid, 'series_instance_uid': row.series_instance_uid,
                 'sop_instance_uid': row.sop_instance_uid} for row in result if
                row.sop_instance_uid not in done_instances]

    progresslogger.info(f'Step 2.1: {len(rev_uids)}')
    n=len(done_instances)
    # Submit args.batch size chunks to process
    all_uuids = rev_uids.copy()
    while rev_uids:
        some_rev_uids = rev_uids[0:args.batch]
        rev_uids = rev_uids[args.batch:]
        task_queue.put((some_rev_uids,n))
        n += args.batch

    for i in range(num_processes):
        task_queue.put('STOP')

    # Wait for process to terminate
    for process in processes:
        print(f'Joining process: {process.name}, {process.is_alive()}')
        process.join()

    return

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    # parser.add_argument('--client', default=storage.Client())
    parser.add_argument('--processes', default=16)
    parser.add_argument('--batch', default=100)
    parser.add_argument('--log_dir', default=settings.LOG_DIR)

    args = parser.parse_args()
    args.id = 0 # Default process ID
    # args.client = storage.Client()

    delete_instances(args)