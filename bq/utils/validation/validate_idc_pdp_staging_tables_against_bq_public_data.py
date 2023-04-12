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

import argparse
import json
import settings

from utilities.logging_config import successlogger, progresslogger,errlogger
from google.cloud import bigquery
from google.api_core.exceptions import NotFound


def skip(args):
    progresslogger.info("Skipped stage")
    return

def schema_has(schema, field_name):
    return next((row for row in schema if row.name == field_name),-1) != -1


def get_table_hash(table_id, excepts):

    client = bigquery.Client()
    try:
        table = client.get_table(table_id)
    except NotFound:
        progresslogger.info(f'{table_id} not found')
        return ""

    # See if the table has any of the 'standard' fields to exclude
    # for field in ['gcs_url', 'aws_url', 'gcs_bucket', 'instance_size']:
    # for field in ['aws_url']:
    #     if schema_has(table.schema, field):
    #         excepts.append(field)
    # if excepts:
    #     except_clause = f"EXCEPT({','.join(excepts)})"
    # else:
    #     except_clause = ""
    except_clause = ""
    query = f"""
    WITH no_urls AS (
        SELECT * {except_clause}
        FROM `{table}`
    )
    SELECT BIT_XOR(DISTINCT FARM_FINGERPRINT(TO_JSON_STRING(t))) as table_hash
    FROM no_urls  AS t
    """

    table_hash =  [dict(row) for row in client.query(query)][0]['table_hash']
    return table_hash
    # job = client.query(query)
    # # Wait for completion
    # result = job.result()
    # return result.json()


if __name__ == '__main__':
    # (sys.argv)
    parser = argparse.ArgumentParser()

    parser.add_argument('--project1', default="bigquery-public-data", help='Project of reference datasets')
    parser.add_argument('--project2', default="idc-pdp-staging", help='Project of pub datasets')
    parser.add_argument('--version2_delta', default=0)
    args = parser.parse_args()

    dones = open(f'{successlogger.handlers[0].baseFilename}').read().splitlines()
    errors = [row.split(':')[-1] for row in open(f'{errlogger.handlers[0].baseFilename}').read().splitlines()]
    progresslogger.info(f'args: {json.dumps(args.__dict__, indent=2)}')

    for dataset_version in [i for i in range(1,14)]:
        if str(dataset_version) in dones:
            continue

        steps = [
            ("dicom_all", 1),
            ("dicom_all_view", 13),
            ("dicom_metadata_curated",5),
            ("dicom_metadata_curated_view",13),
            ("dicom_metadata_curated_series_level",13),
            ("dicom_metadata_curated_series_level_view",13),
            ("measurement_groups",2),
            ("measurement_groups_view",13),
            ("qualitative_measurements",2),
            ("qualitative_measurements_view",13),
            ("quantitative_measurements",2),
            ("quantitative_measurements_view",13),
            ("segmentations",1),
            ("segmentations_view",13),
            ("dicom_derived_all",1),
            ("auxiliary_metadata", 1),
            (f"dicom_pivot_v{dataset_version}", 1),
        ]
        
        for table_name, min_version in steps:
            # if (table_name == 'dicom_derived_all') & (int(dataset_version) < 4):
            #     continue
            ref_name = f'{args.project1}.idc_v{dataset_version}.{table_name}'
            if dataset_version >= min_version:
                # See if we've already done this table/view
                index = next((index for index, row in enumerate(dones) if row.split(',')[0] == ref_name), -1)
                excepts = []
                project = args.project2
                if dataset_version < 8 or project != 'idc-dev-etl':
                    full_name = f'{project}.idc_v{dataset_version+args.version2_delta}.{table_name}'
                else:
                    full_name = f'{project}.idc_v{dataset_version+args.version2_delta}_pub.{table_name}'
                if full_name not in dones and full_name not in errors:

                    ref_hash = get_table_hash(
                        ref_name,
                        excepts
                    )
                    # Validate the view in prod
                    test_hash = get_table_hash( \
                        full_name,
                        excepts)
                    progresslogger.info(f'{ref_name}:{ref_hash}, {full_name}:{test_hash}')
                    if str(ref_hash) == str(test_hash):
                        successlogger.info(full_name)
                    else:
                        errlogger.error(full_name)
                else:
                    progresslogger.info(f'Skipping {full_name} previously verified')

            else:
                progresslogger.info(f'Skipping {ref_name} not in this version')

        # successlogger.info(dataset_version)

