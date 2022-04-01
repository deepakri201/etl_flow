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

import os
import argparse
import logging
from logging import INFO
from google.cloud import bigquery, storage
import json
from hfs.gen_study_blobs import gen_study_object


# Copy the blobs that are new to a version from dev pre-staging buckets
# to dev staging buckets.

def get_studies_in_patient(args, uuid):
    client = bigquery.Client()
    query = f"""
    SELECT
      distinct
      study_instance_uid,
      st_uuid uuid,
      st_hashes.all_hash md5_hash,
      st_init_idc_version init_idc_version,
      st_rev_idc_version rev_idc_version,
      st_final_idc_version final_idc_version
    FROM
      `idc-dev-etl.whc_dev.hfs_all_joined`
    WHERE
      p_uuid = '{uuid}'
    ORDER BY study_instance_uid
    """
    # urls = list(client.query(query))
    query_job = client.query(query)  # Make an API request.
    query_job.result()  # Wait for the query to complete.
    destination = query_job.destination
    destination = client.get_table(destination)
    return destination

# def get_parents_of_patient(args, uuid):
#     client = bigquery.Client()
#     query = f"""
#     SELECT
#       distinct
#       c_uuid uuid
#     FROM
#       `idc-dev-etl.whc_dev.hfs_all_joined`
#     WHERE
#       p_uuid = {uuid}
#     """
#     # urls = list(client.query(query))
#     query_job = client.query(query)  # Make an API request.
#     query_job.result()  # Wait for the query to complete.
#     destination = query_job.destination
#     destination = client.get_table(destination)
#     return destination


def gen_patient_object(args,
            submitter_case_id,
            idc_case_id,
            p_uuid,
            md5_hash,
            init_idc_version,
            rev_idc_version,
            final_idc_version):
    bq_client = bigquery.Client()
    destination = get_studies_in_patient(args, p_uuid)
    studies = [study for page in bq_client.list_rows(destination, page_size=args.batch).pages for study in page ]
    # destination = get_parents_of_patient(args, p_uuid)
    # collections = [collection for page in bq_client.list_rows(destination, page_size=args.batch).pages for collection in page ]

    patient = {
        "encoding": "v1",
        "object_type": "patient",
        "submitter_case_id": submitter_case_id,
        "idc_case_id": idc_case_id,
        "uuid": p_uuid,
        "md5_hash": md5_hash,
        "init_idc_version": init_idc_version,
        "rev_idc_version": rev_idc_version,
        "final_idc_version": final_idc_version,
        "self_uri": f"gs://{args.dst_bucket.name}/{p_uuid}.idc",
        "studies": {
            "gs":{
                "region": "us-central1",
                "urls":
                    {
                        "bucket": f"{args.dst_bucket.name}",
                        "blobs":
                            [
                                {"StudyInstanceUID": f"{study.study_instance_uid}",
                                 "blob_name": f"{study.uuid}.idc"} for study in studies
                            ]
                    }
                },
            "drs":{
                "urls":
                    {
                        "server": "drs://nci-crdc.datacommons.io",
                        "object_ids":
                            [f"dg.4DFC/{study.uuid}" for study in studies]
                    }
                }
            }
        }
    blob = args.dst_bucket.blob(f"{p_uuid}.idc").upload_from_string(json.dumps(patient))
    for study in studies:
        gen_study_object(args,
            study.study_instance_uid,
            study.uuid,
            study.md5_hash,
            study.init_idc_version,
            study.rev_idc_version,
            study.final_idc_version)
    print(f'\t\t\tPatient {submitter_case_id}')

    return