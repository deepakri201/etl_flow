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

"""
Add an aws_url column to dicom_derived_metadata table
"""
import settings
import argparse
import json
import time
from google.cloud import bigquery
from google.cloud.bigquery import SchemaField
from google.cloud.exceptions import NotFound
from google.api_core.exceptions import NotFound
from utilities.logging_config import successlogger, progresslogger, errlogger


# args.trg_project: idc_pdp_staging
# args.trg_dataset: idc_vX
# We do a table update rather than regenerate the entire table.
# This is necessary so that we do not need the SQL for each IDC version
def add_aws_url_column_to_dicom_derived_all(args, dones):
    if f'add_aws_url_column_to_dicom_derived_all_{args.trg_dataset}' not in dones:
        table_name = "dicom_derived_all"
        client = bigquery.Client()
        table_id = f'{args.trg_project}.{args.trg_dataset}.{table_name}'
        try:
            table = client.get_table(table_id)
        except:
            exit(-1)

        # Add the aws_url column if we have not already done so
        if next((index for index, field in enumerate(table.schema) if field.name == 'aws_url'), -1) == -1:
            # We only add aws_url if the table has a gcs_url column
            if next((index for index, field in enumerate(table.schema) if field.name == 'gcs_url'), -1 ) != -1:
                client = bigquery.Client()
                query = f"""
                ALTER TABLE `{args.trg_project}.{args.trg_dataset}.{table_name}`
                ADD COLUMN aws_url STRING;
                """
                job = client.query(query)
                # Wait for completion
                result = job.result()

                progresslogger.info(f'Added aws_url column to {table_name}')
            else:
                progresslogger.info(f'No gcs_url column in {table_name}')
        successlogger.info(f'add_aws_url_column_to_dicom_derived_all_{args.trg_dataset}')
    else:
        progresslogger.info(f'Skipping add_aws_url_column_to_dicom_derived_all_{args.trg_dataset}')
    return


# if __name__ == '__main__':
#     # (sys.argv)
#     parser = argparse.ArgumentParser()
#
#     # parser.add_argument('--version', default=settings.CURRENT_VERSION, help='IDC version number')
#     # parser.add_argument('--project', default="idc-dev-etl", help='Project in which tables live')
#     # # parser.add_argument('--dataset', default=f"idc_v{settings.CURRENT_VERSION}_pub", help="BQ dataset")
#     # parser.add_argument('--trg_dataset', default=f"whc_dev_idc_v13_pub", help="BQ target dataset")
#     # args = parser.parse_args()
#     #
#     # progresslogger.info(f'args: {json.dumps(args.__dict__, indent=2)}')
#     #
#     # add_aws_url_column_to_dicom_derived_all(args)
