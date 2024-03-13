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

# Generate a table of TCIA pathology metadata packages

import argparse
import sys
import json
from utilities.tcia_helpers import get_all_tcia_metadata
from google.cloud import bigquery
from utilities.bq_helpers import load_BQ_from_json
from bq.generate_tables_and_views.original_collections_metadata.schema import data_collections_metadata_schema
from utilities.logging_config import errlogger
from python_settings import settings

pathology_data_schema = [
    bigquery.SchemaField('idc_collection_id', 'STRING', mode='NULLABLE', description='IDC collection_id'),
    bigquery.SchemaField('download_id', 'STRING', mode='NULLABLE', description='Collection manager id of this download'),
    bigquery.SchemaField('download_slug', 'STRING', mode='NULLABLE', description='Collection manager slug of this download'),
    bigquery.SchemaField('collection_id', 'STRING', mode='NULLABLE', description='Collection manager id of this collection'),
    bigquery.SchemaField('collection_slug', 'STRING', mode='NULLABLE', description='Collection manager of this collection'),
    bigquery.SchemaField('date_updated', 'DATE', mode='NULLABLE', description='?'),
    bigquery.SchemaField('download_title', 'STRING', mode='NULLABLE', description='Download title'),
    bigquery.SchemaField('file_type', 'STRING', mode='NULLABLE', description='File type'),
    bigquery.SchemaField('download_size', 'STRING', mode='NULLABLE', description='Download size'),
    bigquery.SchemaField('download_size_unit', 'STRING', mode='NULLABLE', description='Download size units'),
    bigquery.SchemaField('download_url', 'STRING', mode='NULLABLE', description='URL from which to download pathology data'),
]

def get_raw_data():
    collections = [ c for c in get_all_tcia_metadata("collections") if c['collection_page_accessibility'] == "Public"]
    downloads = get_all_tcia_metadata("downloads")
    pathology_downloads = {download['id']:download for download in downloads if download['download_type']=='Pathology Images'}
    for collection in collections:
        for id in collection['collection_downloads']:
            if id in pathology_downloads:
                pathology_downloads[id]['collection_id'] = collection['id']
                pathology_downloads[id]['collection_slug'] = collection['slug']

    # Find any pathology downloads for which there is no collection
    for d_id, d_data in pathology_downloads.items():
        if 'collection_slug' not in d_data:
            print(f"No collection_slug for pathology_download {d_data['id']}:{d_data['slug']}")
            try:
                for c_id,v in enumerate(collections):
                    if d_data['slug'].startswith(v['slug']):
                # c_id = next(i for i,v in enumerate(collections) if d_data['slug'].startswith(v['slug']))
                        print(f'\tParent collection {collections[c_id]["id"]}:{collections[c_id]["slug"]}:{collections[c_id]["collection_downloads"]}')
            except:
                print(f"No collection found for {d_data['slug']}")

    pathology_data = []
    for id, data in pathology_downloads.items():
        if 'collection_slug' in data:
            download = dict(
                idc_collection_id = data["collection_slug"].replace('-','_'),
                download_id = id,
                download_slug = data['slug'],
                collection_id = data["collection_id"],
                collection_slug = data["collection_slug"],
                date_updated = data["date_updated"],
                download_title = str(data["download_title"]),
                file_type = str(data["file_type"]),
                download_size = str(data["download_size"]),
                download_size_unit = data["download_size_unit"],
                download_url = data["download_url"] if data["download_url"].startswith('https') else \
                        f'https://www.cancerimagingarchive.net{data["download_url"]}'
            )
            pathology_data.append(download)

    metadata_json = '\n'.join([json.dumps(row) for row in
                        sorted(pathology_data, key=lambda d: d['download_slug'])])
    try:
        BQ_client = bigquery.Client(project=settings.DEV_PROJECT)
        load_BQ_from_json(BQ_client,
                    settings.DEV_PROJECT,
                    settings.BQ_DEV_INT_DATASET , args.bqtable_name, metadata_json,
                                pathology_data_schema, write_disposition='WRITE_TRUNCATE')
        pass
    except Exception as exc:
        errlogger.error(f'Table creation failed: {exc}')
        exit


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--bqtable_name', default='tcia_pathology_metadata', help='BQ table name')

    args = parser.parse_args()
    print("{}".format(args), file=sys.stdout)

    get_raw_data()