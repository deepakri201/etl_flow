#
# Copyright 2020, Institute for Systems Biology
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

import json
import sys
from subprocess import run, PIPE
import time, datetime
from io import StringIO
import requests
import logging

from python_settings import settings


TIMEOUT=3600
CHUNK_SIZE=1024*1024

TCIA_URL = 'https://services.cancerimagingarchive.net/services/v4/TCIA/query'
NBIA_URL = 'https://services.cancerimagingarchive.net/nbia-api/services/v1'


# @backoff.on_exception(backoff.expo,
#                       requests.exceptions.RequestException,
#                       max_tries=3)
def get_url(url):  # , headers):
    result =  requests.get(url)  # , headers=headers)
    if result.status_code != 200:
        raise RuntimeError('In get_url(): status_code=%s; url: %s', result.status_code, url)
    return result

def TCIA_API_request(endpoint, parameters="", nbia_server=True):
    server_url = NBIA_URL if nbia_server else TCIA_URL
    url = f'{server_url}/{endpoint}?{parameters}'
    results = get_url(url)
    results.raise_for_status()
    return results.json()


def TCIA_API_request_to_file(filename, endpoint, parameters="", nbia_server=True):
    server_url = NBIA_URL if nbia_server else TCIA_URL
    url = f'{server_url}/{endpoint}?{parameters}'
    begin = time.time()
    results = get_url(url)
    results.raise_for_status()
    with open(filename, 'wb') as f:
        f.write(results.content)
    duration = str(datetime.timedelta(seconds=(time.time() - begin)))
    logging.debug('File %s downloaded in %s',filename, duration)
    return 0


def get_collections(nbia_server=True):
    server_url = NBIA_URL if nbia_server else TCIA_URL
    url = f'{server_url}/getCollectionValues'
    results = get_url(url)
    collections = results.json()
    # collections = [collection['Collection'].replace(' ', '_') for collection in results.json()]
    return collections


def get_TCIA_patients_per_collection(collection_id, nbia_server=True):
    server_url = NBIA_URL if nbia_server else TCIA_URL
    url = f'{server_url}/getPatient?Collection={collection_id}'
    results = get_url(url)
    patients = results.json()
    return patients


def get_TCIA_studies_per_patient(collection, patientID, nbia_server=True):
    server_url = NBIA_URL if nbia_server else TCIA_URL
    url = f'{server_url}/getPatientStudy?Collection={collection}&PatientID={patientID}'
    results = get_url(url)
    studies = results.json()
    return studies


def get_TCIA_studies_per_collection(collection, nbia_server=True):
    server_url = NBIA_URL if nbia_server else TCIA_URL
    url = f'{server_url}/getPatientStudy?Collection={collection}'
    results = get_url(url)
    studies = results.json()
    return studies


def get_TCIA_series_per_study(collection, patientID, studyInstanceUID, nbia_server=True):
    server_url = NBIA_URL if nbia_server else TCIA_URL
    url = f'{server_url}/getSeries?Collection ={collection}&PatientID={patientID}&StudyInstanceUID={studyInstanceUID}'
    results = get_url(url)
    series = results.json()
    return series

def get_TCIA_instance_uids_per_series(seriesInstanceUID, nbia_server=True):
    server_url = NBIA_URL if nbia_server else TCIA_URL
    url = f'{server_url}/getSOPInstanceUIDs?SeriesInstanceUID={seriesInstanceUID}'
    results = get_url(url)
    instance_uids = results.json()
    return instance_uids

def get_TCIA_instance(seriesInstanceUID, sopInstanceUID, nbia_server=True):
    server_url = NBIA_URL if nbia_server else TCIA_URL
    url = f'{server_url}/getSingleImage?SeriesInstanceUID={seriesInstanceUID}&SOPInstanceUID={sopInstanceUID}'
    results = get_url(url)
    instances = results.json()
    return instances

# def get_TCIA_series_per_collection(collection):
#     results = TCIA_API_request('getSeries')
#     SeriesInstanceUIDs = [SeriesInstanceUID['SeriesInstanceUID'] for SeriesInstanceUID in results]
#     return SeriesInstanceUIDs

def get_TCIA_series_per_collection(collection, nbia_server=True):
    server_url = NBIA_URL if nbia_server else TCIA_URL
    url = f'{server_url}/getSeries?Collection={collection}'
    results = get_url(url)
    series = results.json()
    return series

def get_TCIA_series(nbia_server=True):
    results = TCIA_API_request('getSeries', nbia_server)
    # We only need a few values
    # We create a revision date field, filled with today's date (UTC +0), until TCIA returns a revision date 
    # in the response to getSeries
    today = datetime.date.today().isoformat()
    data = [{'CollectionID':result['Collection'],
          'StudyInstanceUID':result['StudyInstanceUID'],
          'SeriesInstanceUID':result['SeriesInstanceUID'],
          "SeriesInstanceUID_RevisionDate":today}
           for result in results]
    
    return data

# def get_TCIA_instances_per_series(dicom, series_instance_uid, nbia_server=True):
#     # Get a zip of the instances in this series to a file and unzip it
#     # result = TCIA_API_request_to_file("{}/{}.zip".format(dicom, series_instance_uid),
#     #             "getImage", parameters="SeriesInstanceUID={}".format(series_instance_uid),
#     #             nbia_server=nbia_server)
#     server_url = NBIA_URL if nbia_server else TCIA_URL
#     url = f'{server_url}/{"getImage"}?SeriesInstanceUID={series_instance_uid}'
#
#     # _bytes=0
#     begin = time.time()
#     with open("{}/{}.zip".format(dicom, series_instance_uid), 'wb') as f:
#         r = session().get(url, stream=True, timeout=TIMEOUT)
#         for chunk in r.iter_content(chunk_size=None):
#             if chunk:
#                 f.write(chunk)
#                 f.flush()
#                 # _bytes += len(chunk)
#     # elapsed = time.time() - begin
#     # print(f'{_bytes} in {elapsed}s: {_bytes/elapsed}B/s; CHUNK_SIZE: {CHUNK_SIZE}')
#     # Now try to extract the instances to a directory DICOM/<series_instance_uid>
#     try:
#         with zipfile.ZipFile("{}/{}.zip".format(dicom, series_instance_uid)) as zip_ref:
#             zip_ref.extractall("{}/{}".format(dicom, series_instance_uid))
#         return
#     except :
#         logging.error("\tZip extract failed for series %s with error %s,%s,%s ", series_instance_uid,
#                       sys.exc_info()[0], sys.exc_info()[1], sys.exc_info()[2])
#         raise


def get_TCIA_instances_per_series(dicom, series_instance_uid, nbia_server=True):
    server_url = NBIA_URL if nbia_server else TCIA_URL
    url = f'{server_url}/{"getImage"}?SeriesInstanceUID={series_instance_uid}'
    f = "{}/{}.zip".format(dicom, series_instance_uid)

    result = run([
        'curl',
        '-o',
        f,
        url
    ], stdout=PIPE, stderr=PIPE)
    # result = json.loads(result.stdout.decode())['access_token']

    # Now try to extract the instances to a directory DICOM/<series_instance_uid>
    try:
        # with zipfile.ZipFile("{}/{}.zip".format(dicom, series_instance_uid)) as zip_ref:
        #     zip_ref.extractall("{}/{}".format(dicom, series_instance_uid))
        result = run([
            'unzip',
            "{}/{}.zip".format(dicom, series_instance_uid),
            '-d',
            "{}/{}".format(dicom, series_instance_uid)
        ], stdout=PIPE, stderr=PIPE)

        return
    except :
        logging.error("\tZip extract failed for series %s with error %s,%s,%s ", series_instance_uid,
                      sys.exc_info()[0], sys.exc_info()[1], sys.exc_info()[2])
        raise


def create_jsonlines_from_list(original):
    in_json = StringIO(json.dumps(original)) 
    result = [json.dumps(record) for record in json.load(in_json)]
    result = '\n'.join(result)
    return result


def get_collection_size(collection, nbia_server=True):
    size = 0
    serieses=TCIA_API_request('getSeries', parameters="Collection={}".format(collection.replace(' ','_')),
                              nbia_server=nbia_server)
    print("{} series in {}".format(len(serieses), collection), flush=True)
    for aseries in serieses:
        seriesSize=TCIA_API_request('getSeriesSize', parameters="SeriesInstanceUID={}".format(aseries['SeriesInstanceUID']),
                            nbia_server=nbia_server)
#             print(seriesSize)
        size += int(float(seriesSize[0]['TotalSizeInBytes']))
        print("{} {}\r".format(aseries['SeriesInstanceUID'], size),end="")
    return size


def get_collection_sizes_in_bytes(nbia_server=True):
    sizes = {}
    collections = get_collections(nbia_server)
    collections.sort(reverse=True)
    for collection in collections:
        sizes[collection] = get_collection_size(collection)
    return sizes


def get_collection_sizes(nbia_server=True):
    collections = get_collections(nbia_server)
    counts = {collection:0 for collection in collections}
    serieses=TCIA_API_request('getSeries', nbia_server)
    for aseries in serieses:
        counts[aseries['Collection']] += int(aseries['ImageCount'])
    sorted_counts = [(k, v) for k, v in sorted(counts.items(), key=lambda item: item[1])]
    return sorted_counts


def get_access_token(url="https://public.cancerimagingarchive.net/nbia-api/oauth/token"):
    data = dict(
        username="nbia_guest",
        password="",
        client_id=settings.TCIA_CLIENT_ID,
        client_secret=settings.TCIA_CLIENT_SECRET,
        grant_type="password")
    # url = "https://public.cancerimagingarchive.net/nbia-api/oauth/token"
    result = requests.post(url, data = data)
    access_token = result.json()
    return access_token

def get_collection_values_and_counts():
    access_token = get_access_token()['access_token']
    headers = dict(
        Authorization = f'Bearer {access_token}'
    )
    url = 'https://services.cancerimagingarchive.net/nbia-api/services/getCollectionValuesAndCounts'
    result = requests.get(url, headers=headers)
    collections = [collection['criteria'] for collection in result.json()]
    return collections


def get_collection_descriptions():
    # Get access token for the guest account
    access_token = get_access_token()
    result = run([
        'curl',
        '-H',
        "Authorization:Bearer {}".format(access_token),
        '-k',
        'https://public.cancerimagingarchive.net/nbia-api/services/getCollectionDescriptions'
        ], stdout=PIPE, stderr=PIPE)
    descriptions = json.loads(result.stdout.decode())
    collection_descriptions = {description['collectionName']: description['description'] for description in descriptions}

    return collection_descriptions


def get_series_info(storage_client, project, bucket_name):
    series_info = {}
    blobs = storage_client.bucket(bucket_name, user_project=project).list_blobs()
    series_info = {blob.name.rsplit('.dcm',1)[0]: {"md5_hash":blob.md5_hash, "size":blob.size} for blob in blobs}
    return series_info

def get_updated_series(date):
    access_token = get_access_token()['access_token']
    headers = dict(
        Authorization = f'Bearer {access_token}'
    )
    url = f'https://services.cancerimagingarchive.net/nbia-api/services/v2/getUpdatedSeries?fromDate={date}'
    result = requests.get(url, headers=headers)
    if result.status_code == 500 and result.text == 'No data found.':
        series = []
    else:
        series = result.json()
    return series


def get_hash(request_data, access_token=None):
    if not access_token:
        access_token = get_access_token(url = "https://public-dev.cancerimagingarchive.net/nbia-api/oauth/token")['access_token']
    headers = dict(
        Authorization = f'Bearer {access_token}'
    )
    url = "https://public-dev.cancerimagingarchive.net/nbia-api/services/getMD5Hierarchy"
    result = requests.post(url, headers=headers, data=request_data)

    return result

def get_images_with_md5_hash(SeriesInstanceUID, access_token=None):
    if not access_token:
        access_token = get_access_token(url = "https://public-dev.cancerimagingarchive.net/nbia-api/oauth/token")['access_token']
    headers = dict(
        Authorization = f'Bearer {access_token}'
    )
    server_url = "https://public-dev.cancerimagingarchive.net/nbia-api/services/v1"
    # server_url = "https://tracker.nci.nih.gov/browse/NBIA-1478"
    url = f'{server_url}/getImageWithMD5Hash?SeriesInstanceUID={SeriesInstanceUID}'
    result = requests.get(url, headers=headers)

    return result


def get_access_token_dev(url="https://public.cancerimagingarchive.net/nbia-api/oauth/token"):
    data = dict(
        username=settings.TCIA_ID,
        password=settings.TCIA_PASSWORD,
        client_id=settings.TCIA_CLIENT_ID,
        client_secret=settings.TCIA_CLIENT_SECRET,
        grant_type="password")
    # url = "https://public.cancerimagingarchive.net/nbia-api/oauth/token"
    result = requests.post(url, data = data)
    access_token = result.json()
    return access_token


def get_patients_per_collection_dev(collection_id):
    access_token = get_access_token_dev(url = "https://nlst.cancerimagingarchive.net/nbia-api/oauth/token")['access_token']
    headers = dict(
        Authorization = f'Bearer {access_token}'
    )

    server_url = 'https://nlst.cancerimagingarchive.net/nbia-api/services/v2'
    url = f'{server_url}/getPatient?Collection={collection_id}'
    results = requests.get(url, headers=headers)
    collections = results.json()
    # collections = [collection['Collection'].replace(' ', '_') for collection in results.json()]
    return collections

def get_collections_dev():
    access_token = get_access_token_dev(url = "https://nlst.cancerimagingarchive.net/nbia-api/oauth/token")['access_token']
    headers = dict(
        Authorization = f'Bearer {access_token}'
    )

    server_url = 'https://nlst.cancerimagingarchive.net/nbia-api/services/v2'
    url = f'{server_url}/getCollectionValues'
    results = requests.get(url, headers=headers)
    collections = results.json()
    # collections = [collection['Collection'].replace(' ', '_') for collection in results.json()]
    return collections

def get_collection_values_and_counts_dev():
    access_token = get_access_token(url = "https://nlst.cancerimagingarchive.net/nbia-api/oauth/token")['access_token']
    headers = dict(
        Authorization = f'Bearer {access_token}'
    )
    url = 'https://nlst.cancerimagingarchive.net/nbia-api/services/v2/getSimpleSearchCriteriaValues'
    result = requests.get(url, headers=headers)
    collections = [collection['criteria'] for collection in result.json()]
    return collections

def v2_api(endpoint, data):
    access_token = get_access_token(url = "https://services.cancerimagingarchive.net/nbia-api/oauth/token")['access_token']
    headers = dict(
        Authorization = f'Bearer {access_token}'
    )
    url = f'https://services.cancerimagingarchive.net/nbia-api/services/{endpoint}'
    result = requests.get(url, headers=headers, data=data)
    # collections = [collection['criteria'] for collection in result.json()]
    return result






if __name__ == "__main__":
    if not settings.configured:
        from python_settings import settings
        import settings as etl_settings

        settings.configure(etl_settings)
        assert settings.configured

    # results = get_collection_values_and_counts()
    # results = v2_api('getCollectionValuesAndCounts', data="")
    # results = v2_api('getSimpleSearchCriteriaValues', data="")
    # results = get_collection_values_and_counts()
    # results = get_collection_values_and_counts_dev()
    results = get_patients_per_collection_dev('NLST')
    results = get_collections_dev()
    # hash = get_hash({"SeriesInstanceUID":'1.3.6.1.4.1.14519.5.2.1.1706.6003.183542674700655712034736428353'})
    # result = get_images_with_md5_hash('1.3.6.1.4.1.14519.5.2.1.1706.6003.183542674700655712034736428353')
    # with open('/home/bcliffor/temp/1.3.6.1.4.1.14519.5.2.1.1706.6003.183542674700655712034736428353.zip', 'wb') as f:
    #     f.write(result.content)

    # series = get_updated_series('20/02/2021')
    # hash = get_hash({"Collection":'TCGA-ESCA'})
    # instances = get_TCIA_instances_per_series('/mnt/disks/idc-etl/temp', '1.2.840.113713.4.2.165042455211102753703326913551133262099', nbia_server=True)
    # print(instances)
    # patients = get_TCIA_patients_per_collection('LDCT-and-Projection-data')
    get_collection_descriptions()
    # series = get_TCIA_series_per_collection('TCGA-BRCA')
    # series = get_updated_series('23/03/2021')
    # print(time.asctime());studies = get_TCIA_studies_per_collection('BREAST-DIAGNOSIS', nbia_server=False);print(time.asctime())
    # studies = get_TCIA_studies_per_patient(collection.tcia_api_collection_id, patient.submitter_case_id)
    # patients=get_TCIA_patients_per_collection('CBIS-DDSM')
    #
    # # collection = get_collection_values_and_counts()
    # nbia_collections = [c['Collection'] for c in get_collections(nbia_server=True)]
    # nbia_collections.sort()
    # nbia_collections = [c['Collection'] for c in get_collections(nbia_server=True)]
    # nbia_collections.sort()
    # tcia_collections = [c['Collection'] for c in get_collections(nbia_server=False)]
    # tcia_collections.sort()
    # pass
    # for collection in collections:
    #     patients = get_TCIA_patients_per_collection(collection['Collection'])
    #     for patient in patients:
    #         studies = get_TCIA_studies_per_patient(collection['Collection'], patient['PatientId'])
    #         for study in studies:
    #             seriess = get_TCIA_series_per_study(collection['Collection'], patient['PatientId'], study['StudyInstanceUID'])
    #             for series in seriess:
    #                 instanceUIDs = get_TCIA_instance_uids_per_series(series['SeriesInstanceUID'])
    #                 for instanceUID in instanceUIDs:
    #                     instance = get_TCIA_instance(series['SeriesInstanceUID'], instanceUID['SOPInstanceUID'])


