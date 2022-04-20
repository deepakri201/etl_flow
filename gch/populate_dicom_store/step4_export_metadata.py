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



# Export metadata from a DICOM store to BQ

import argparse
import sys
import json
import requests
import subprocess
import time
from subprocess import PIPE
from google.cloud import bigquery
from googleapiclient.errors import HttpError
from google.api_core.exceptions import NotFound
from utilities.bq_helpers import create_BQ_dataset, copy_BQ_table
from python_settings import settings


def export_dicom_metadata(args):
    # Get an access token
    results = subprocess.run(['gcloud', 'auth', 'application-default', 'print-access-token'], stdout=PIPE, stderr=PIPE)
    bearer = str(results.stdout,encoding='utf-8').strip()

    # BQ table to which to export metadata
    destination = f'bq://{settings.DEV_PROJECT}.{settings.BQ_DEV_EXT_DATASET}.{args.bqtable}'
    data = {
        'bigqueryDestination': {
            'tableUri': destination,
            'writeDisposition': 'WRITE_TRUNCATE'
        }
    }

    headers = {
        'Authorization': f'Bearer {bearer}',
        'Content-Type': 'application/json; charset=utf-8'
    }
    url = f'https://healthcare.googleapis.com/v1/projects/{settings.PUB_PROJECT}/locations/{settings.GCH_REGION}/datasets/{settings.GCH_DATASET}/dicomStores/{settings.GCH_DICOMSTORE}:export'
    results = requests.post(url, headers=headers, json=data)

    # Get the operation ID so we can track progress
    operation_id = results.json()['name'].split('/')[-1]
    print("Operation ID: {}".format(operation_id))

    while True:
        # Get an access token. This can be a long running job. Just get a new one every time.
        results = subprocess.run(['gcloud', 'auth', 'application-default', 'print-access-token'], stdout=PIPE, stderr=PIPE)
        bearer = str(results.stdout, encoding='utf-8').strip()

        headers = {
            'Authorization': f'Bearer {bearer}'
        }
        url = f'https://healthcare.googleapis.com/v1/projects/{settings.PUB_PROJECT}/locations/{settings.GCH_REGION}/datasets/{settings.GCH_DATASET}/operations/{operation_id}'
        results = requests.get(url, headers=headers)

        details = results.json()

        # The result is JSON that will include a "done" element with status when the op us complete
        if 'done' in details and details['done']:
            if 'error' in details:
                print('Done with errorcode: {}, message: {}'.format(details['error']['code'], details['error']['message']))
            else:
                print(details)
            break
        else:
            print(details)
            time.sleep(5*60)

def get_job(args):
    results = subprocess.run(['gcloud', 'auth', 'application-default', 'print-access-token'], stdout=PIPE, stderr=PIPE)
    bearer = str(results.stdout, encoding='utf-8').strip()

    headers = {
        'Authorization': f'Bearer {bearer}'
    }
    url = f'https://healthcare.googleapis.com/v1/projects/{settings.GCH_DICOMSTORE}/locations/{settings.GCH_REGION}/datasets/{settings.GCH_DATASET}/operations'
    results = requests.get(url, headers=headers)
    # Get the operation ID so we can track progress
    operation_id = results.json()['operations'][0]['name'].split('/')[-1]
    print("Operation ID: {}".format(operation_id))

    while True:
        # Get an access token. This can be a long running job. Just get a new one every time.
        results = subprocess.run(['gcloud', 'auth', 'application-default', 'print-access-token'], stdout=PIPE, stderr=PIPE)
        bearer = str(results.stdout, encoding='utf-8').strip()

        headers = {
            'Authorization': f'Bearer {bearer}'
        }
        url = f'https://healthcare.googleapis.com/v1/projects/{settings.GCH_DICOMSTORE}/locations/{settings.GCH_REGION}/datasets/{settings.GCH_DATASET}/operations/{operation_id}'
        results = requests.get(url, headers=headers)

        details = results.json()

        # The result is JSON that will include a "done" element with status when the op us complete
        if 'done' in details and details['done']:
            if 'error' in details:
                print('Done with errorcode: {}, message: {}'.format(details['error']['code'], details['error']['message']))
            else:
                print('Done')
            break
        else:
            print(details)
            time.sleep(5*60)

def export_metadata(args):
    client = bigquery.Client(project=settings.DEV_PROJECT)
    # Create the BQ dataset if it does not already exist
    try:
        dst_dataset = client.get_dataset(settings.BQ_DEV_EXT_DATASET)
    except NotFound:
        dst_dataset = create_BQ_dataset(client, settings.BQ_DEV_EXT_DATASET, settings.dataset_description)

    try:
        start = time.time()
        response=export_dicom_metadata(args)
        finished = time.time()
        elapsed = finished - start
        print('Elapsed time: {}'.format(elapsed))

    except HttpError as e:
        err=json.loads(e.content)
        print(f'Error {e}')


if __name__ == '__main__':
    parser =argparse.ArgumentParser()
    parser.add_argument('--bqtable', default='dicom_metadata', help="BQ table name")
    parser.add_argument('--dataset_description', default = f'IDC V{settings.CURRENT_VERSION} BQ tables and views')

    args = parser.parse_args()
    print("{}".format(args), file=sys.stdout)
    # get_job(args)
    export_metadata(args)
