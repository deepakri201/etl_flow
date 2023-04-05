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


def skip(args):
    progresslogger.info("Skipped stage")
    return

def schema_has(schema, field_name):
    return next((row for row in schema if row.name == field_name),-1) != -1


def get_table_hash(table_id, excepts):

    client = bigquery.Client()
    table = client.get_table(table_id)

    # See if the table has any of the 'standard' fields to exclude
    for field in ['gcs_url', 'aws_url', 'gcs_bucket', 'instance_size']:
        if schema_has(table.schema, field):
            excepts.append(field)
    if excepts:
        except_clause = f"EXCEPT({','.join(excepts)})"
    else:
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

    parser.add_argument('--ref_project', default="bigquery-public-data", help='Project of reference datasets')
    parser.add_argument('--dev_project', default="idc-dev-etl", help='Project of dev datasets')
    parser.add_argument('--pub_project', default="idc-dev-etl", help='Project of pub datasets')
    args = parser.parse_args()

    dones = open(f'{successlogger.handlers[0].baseFilename}').read().splitlines()
    errors = [row.split(':')[-1] for row in open(f'{errlogger.handlers[0].baseFilename}').read().splitlines()]

    for dataset_version in [str(i) for i in range(13,14)]:
        if dataset_version in dones:
            continue
        progresslogger.info(f'args: {json.dumps(args.__dict__, indent=2)}')

        steps = [
            # ("dicom_all", True, 1),
            # ("dicom_all_view", True, 13),
            # ("dicom_metadata_curated", False, 5),
            # ("dicom_metadata_curated_view", False, 13),
            # ("dicom_metadata_curated_series_level", False, 13),
            # ("dicom_metadata_curated_series_level_view", False, 13),
            ("measurement_groups", False, 1),
            ("measurement_groups_view", False, 13),
            ("qualitative_measurements", False, 2),
            ("qualitative_measurements_view", False, 13),
            ("quantitative_measurements", False, 2),
            ("quantitative_measurements_view", False, 13),
            ("segmentations", False, 1),
            ("segmentations_view", False, 13),
            ("dicom_derived_all", False, 1),
            (f"dicom_pivot_v{dataset_version}", True, 1),
            # ("auxiliary_metadata", True, 1),
        ]
        
        for table_name, has_urls, min_version in steps:
            # if (table_name == 'dicom_derived_all') & (int(dataset_version) < 4):
            #     continue
            ref_name = f'{args.ref_project}.idc_v{dataset_version}.{table_name}'
            if int(dataset_version) >= min_version:
                # See if we've already done this table/view
                index = next((index for index, row in enumerate(dones) if row.split(',')[0] == ref_name), -1)
                if index == -1:
                    excepts = []
                    ref_hash = get_table_hash(
                        ref_name,
                        excepts
                    )
                    successlogger.info(f'{ref_name},{ref_hash}')
                else:
                    # We already computed the ref hash. Get it for comparison
                    ref_hash = dones[index].split(',')[1]

                # Validate the view in prod
                excepts = []
                project = args.pub_project
                if int(dataset_version) < 8:
                    full_name = f'{project}.idc_v{dataset_version}.{table_name}'
                else:
                    full_name = f'{project}.idc_v{dataset_version}_pub.{table_name}'
                if full_name not in dones and full_name not in errors:
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

