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
from collections import OrderedDict
from utilities.logging_config import successlogger, progresslogger,errlogger
from google.cloud import bigquery,storage


def skip(args):
    progresslogger.info("Skipped stage")
    return

def types_match(schema, name, field_type):
    match = field_type == next((row for row in schema if row.name.lower() ==name.lower())).field_type
    return match

def schema_has(schema, field_name):
    return next((row for row in schema if row.name.lower() == field_name.lower()),-1) != -1


def gen_select(client, table_id_1, excepts, table_id_2):
    table_1 = client.get_table(table_id_1)
    table_2 = client.get_table(table_id_2)

    schema_1 = table_1.schema
    schema_2 = table_2.schema

    flatten = []
    for name in excepts:
        progresslogger.info(f'Excluded {name} from both tables')
    for row in schema_1:
        if not schema_has(schema_2, row.name):
            progresslogger.info(f'Excluded {table_id_1}:{row.name}')
            excepts.append(row.name)
        elif not types_match(schema_2, row.name, row.field_type):
            progresslogger.info(f'Excluded field {row.name} for type mismatch')
            excepts.append(row.name)
        elif row.field_type == 'RECORD':
            progresslogger.info(f'Excluded RECORD {row.name}')
            excepts.append(row.name)
        elif row.mode == 'REPEATED' and not row.field_type=='RECORD':
            flatten.append(f'CROSS JOIN UNNEST({row.name}) AS {row.name}')

    for row in schema_2:
        if not schema_has(schema_1, row.name):
            progresslogger.info(f'Excluded {table_id_2}:{row.name}')

    selects = [row.name for row in schema_1]

    try:
        for name in excepts:
            if name in selects:
                selects.remove(name)
    except Exception as exc:
        pass

    # Always remove gcs_url, aws_url
    if 'gcs_url' in selects:
        selects.remove('gcs_url')
    if 'aws_url' in selects:
        selects.remove('aws_url')

    selects = ','.join(selects)

    flattens = '\n\t  '.join(flatten)

    return selects, flattens



def compare(table_1, excepts, table_2, order_by):

    client = bigquery.Client()

    progresslogger.info(f'{table_1}:{table_2}')

    # Exclude columns that are not common to both tables
    select, flattens = gen_select(client, table_1, excepts, table_2 )

    query = f"""
  (
  WITH
    t1 AS (
    SELECT DISTINCT
      {select}
    FROM
      `{table_1}` 
      {flattens}
    EXCEPT DISTINCT
    SELECT DISTINCT
      {select}
    FROM
      `{table_2}`
      {flattens})
  SELECT DISTINCT
    't1' AS src,
    t1.*,
  FROM
    t1)
UNION ALL (
  WITH
    t2 AS (
    SELECT
      {select}
    FROM
      `{table_2}` 
      {flattens}
    EXCEPT DISTINCT
    SELECT
      {select}
    FROM
      `{table_1}`
      {flattens})
  SELECT
    't2' AS src,
    t2.*
  FROM
    t2)
ORDER BY
  SeriesInstanceUID,
  SOPInstanceUID,
  src
   """

    table_hash =  [dict(row) for row in client.query(query)][0]['table_hash']
    return table_hash

if __name__ == '__main__':
    parser = argparse.ArgumentParser()

    parser.add_argument('--table1', default="bigquery-public-data.idc_v4.dicom_pivot_v4")
    parser.add_argument('--except_clause', default = [])
    parser.add_argument('--table2', default="idc-pdp-staging.idc_v4.dicom_pivot_v4")
    parser.add_argument('--order_by', default='SeriesInstanceUID,  SOPInstanceUID, src')
    args = parser.parse_args()

    compare(args.table1, args.except_clause, args.table2, args.order_by)