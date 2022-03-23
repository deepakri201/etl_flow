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

# This script generates the BQ auxiliary_metadata table. It basically joins the BQ version, collection,
# patient, study, series, and instance tables. Typically these are uploaded from PostgreSQL to BQ using
# the upload_psql_to_bq.py script
import argparse
import sys
from google.cloud import bigquery
from utilities.bq_helpers import load_BQ_from_json, query_BQ

def gen_aux_table(args):
    query = f"""
WITH
  collection_access AS (
  SELECT DISTINCT m.idc_collection_id, o.premerge_tcia_url, o.premerge_path_url, o.{args.target}_url as url, o.access
  FROM
    `idc-dev-etl.{args.dev_bqdataset_name}.version` as v
  JOIN 
    `idc-dev-etl.{args.dev_bqdataset_name}.version_collection` vc
  ON
    v.version = vc.version
  JOIN
    `idc-dev-etl.{args.dev_bqdataset_name}.collection` c
  ON
    vc.collection_uuid = c.uuid
  JOIN
    `idc-dev-etl.{args.dev_bqdataset_name}.open_collections` as o
  ON
    REPLACE(REPLACE(LOWER(c.collection_id),' ','_'),'-','_') = REPLACE(REPLACE(LOWER(o.tcia_api_collection_id ),' ','_'),'-','_') 
  JOIN
    `idc-dev-etl.{args.dev_bqdataset_name}.collection_id_map` as m
  ON REPLACE(REPLACE(LOWER(o.tcia_api_collection_id),'-','_'), ' ','_') = REPLACE(REPLACE(LOWER(m.idc_webapp_collection_id),'-','_'), ' ','_')
  WHERE v.version = 8

  UNION ALL

  SELECT DISTINCT m.idc_collection_id, cr.premerge_tcia_url, cr.premerge_path_url, cr.{args.target}_url as url, cr.access
  FROM
    `idc-dev-etl.{args.dev_bqdataset_name}.version` as v
  JOIN 
    `idc-dev-etl.{args.dev_bqdataset_name}.version_collection` vc
  ON
    v.version = vc.version
  JOIN
    `idc-dev-etl.{args.dev_bqdataset_name}.collection` c
  ON
    vc.collection_uuid = c.uuid
  JOIN
    `idc-dev-etl.{args.dev_bqdataset_name}.cr_collections` as cr
  ON
    REPLACE(REPLACE(LOWER(c.collection_id),' ','_'),'-','_') = REPLACE(REPLACE(LOWER(cr.tcia_api_collection_id ),' ','_'),'-','_') 
  JOIN
    `idc-dev-etl.{args.dev_bqdataset_name}.collection_id_map` as m
  ON REPLACE(REPLACE(LOWER(cr.tcia_api_collection_id),'-','_'), ' ','_') = REPLACE(REPLACE(LOWER(m.idc_webapp_collection_id),'-','_'), ' ','_')
  WHERE v.version = 8

  UNION ALL

  SELECT DISTINCT m.idc_collection_id, r.premerge_tcia_url, r.premerge_path_url, r.{args.target}_url as url, r.access
  FROM
    `idc-dev-etl.{args.dev_bqdataset_name}.version` as v
  JOIN 
    `idc-dev-etl.{args.dev_bqdataset_name}.version_collection` vc
  ON
    v.version = vc.version
  JOIN
    `idc-dev-etl.{args.dev_bqdataset_name}.collection` c
  ON
    vc.collection_uuid = c.uuid
  JOIN
    `idc-dev-etl.{args.dev_bqdataset_name}.redacted_collections` as r
  ON
    REPLACE(REPLACE(LOWER(c.collection_id),' ','_'),'-','_') = REPLACE(REPLACE(LOWER(r.tcia_api_collection_id ),' ','_'),'-','_') 
  JOIN
    `idc-dev-etl.{args.dev_bqdataset_name}.collection_id_map` as m
  ON REPLACE(REPLACE(LOWER(r.tcia_api_collection_id),'-','_'), ' ','_') = REPLACE(REPLACE(LOWER(m.idc_webapp_collection_id),'-','_'), ' ','_')
  WHERE v.version = 8
 
  UNION ALL

  SELECT DISTINCT m.idc_collection_id, d.premerge_tcia_url, d.premerge_path_url, d.{args.target}_url as url, d.access
  FROM
    `idc-dev-etl.{args.dev_bqdataset_name}.version` as v
  JOIN 
    `idc-dev-etl.{args.dev_bqdataset_name}.version_collection` vc
  ON
    v.version = vc.version
  JOIN
    `idc-dev-etl.{args.dev_bqdataset_name}.collection` c
  ON
    vc.collection_uuid = c.uuid
  JOIN
    `idc-dev-etl.{args.dev_bqdataset_name}.defaced_collections` as d
  ON
    REPLACE(REPLACE(LOWER(c.collection_id),' ','_'),'-','_') = REPLACE(REPLACE(LOWER(d.tcia_api_collection_id ),' ','_'),'-','_') 
  JOIN
    `idc-dev-etl.{args.dev_bqdataset_name}.collection_id_map` as m
  ON REPLACE(REPLACE(LOWER(d.tcia_api_collection_id),'-','_'), ' ','_') = REPLACE(REPLACE(LOWER(m.idc_webapp_collection_id),'-','_'), ' ','_')
  WHERE v.version = 8
  ),
  license_info AS (
  SELECT
    DOI, URL,
    license_url,
    license_long_name,
    license_short_name
  FROM
    `idc-dev-etl.{args.pub_bqdataset_name}.original_collections_metadata`
  UNION ALL
  SELECT
    DOI, "" AS URL,
    license_url,
    license_long_name,
    license_short_name
  FROM
    `idc-dev-etl.{args.pub_bqdataset_name}.analysis_results_metadata` )
SELECT
  c.collection_id AS tcia_api_collection_id,
  REPLACE(REPLACE(LOWER(c.collection_id),'-','_'), ' ','_') AS idc_webapp_collection_id,
  c.min_timestamp as collection_timestamp,
  c.hashes.all_hash AS collection_hash,
  c.init_idc_version AS collection_init_idc_version,
  c.rev_idc_version AS collection_revised_idc_version,
  collection_access.access AS access,
--
  p.submitter_case_id AS submitter_case_id,
  p.idc_case_id AS idc_case_id,
  p.hashes.all_hash AS patient_hash,
  p.init_idc_version AS patient_init_idc_version,
  p.rev_idc_version AS patient_revised_idc_version,
--
  st.study_instance_uid AS StudyInstanceUID,
  st.uuid AS study_uuid,
  st.study_instances AS study_instances,
  st.hashes.all_hash AS study_hash,
  st.init_idc_version AS study_init_idc_version,
  st.rev_idc_version AS study_revised_idc_version,
--
  se.series_instance_uid AS SeriesInstanceUID,
  se.uuid AS series_uuid,
  IF(c.collection_id='APOLLO', '', se.source_doi) AS source_doi,
  se.source_url AS source_url,
  se.series_instances AS series_instances,
  se.hashes.all_hash AS series_hash,
  se.init_idc_version AS series_init_idc_version,
  se.rev_idc_version AS series_revised_idc_version,
--
  i.sop_instance_uid AS SOPInstanceUID,
  i.uuid AS instance_uuid,
  CONCAT('gs://',
    # If we are generating gcs_url for the public auxiliary_metadata table 
    if('{args.target}' = 'pub', 
        collection_access.url, 
    #else 
        # We are generating the dev auxiliary_metadata
        # If this instance is new in this version and we 
        # have not merged new instances into dev buckets
        if(i.rev_idc_version = {args.version} and not {args.merged},
            # We use the premerge url prefix
            if(i.source = 'tcia', 
                collection_access.premerge_tcia_url, 
            #else 
                collection_access.premerge_path_url), 
        #else
            # This instance is not new so use the staging bucket prefix
            collection_access.url)), 
    '/', i.uuid, '.dcm') as gcs_url,
  i.size AS instance_size,
  i.hash AS instance_hash,
  i.init_idc_version AS instance_init_idc_version,
  i.rev_idc_version AS instance_revised_idc_version,
  li.license_url AS license_url,
  li.license_long_name AS license_long_name,
  li.license_short_name AS license_short_name

  FROM
    `{args.src_project}.{args.dev_bqdataset_name}.version` AS v
  JOIN
    `{args.src_project}.{args.dev_bqdataset_name}.version_collection` AS vc
  ON
    v.version = vc.version
  JOIN
    `{args.src_project}.{args.dev_bqdataset_name}.collection` AS c
  ON
    vc.collection_uuid = c.uuid
  JOIN
    `{args.src_project}.{args.dev_bqdataset_name}.collection_patient` AS cp
  ON
    c.uuid = cp.collection_uuid
  JOIN
    `{args.src_project}.{args.dev_bqdataset_name}.patient` AS p
  ON
    cp.patient_uuid = p.uuid
  JOIN
    `{args.src_project}.{args.dev_bqdataset_name}.patient_study` AS ps
  ON
    p.uuid = ps.patient_uuid
  JOIN
    `{args.src_project}.{args.dev_bqdataset_name}.study` AS st
  ON
    ps.study_uuid = st.uuid
  JOIN
    `{args.src_project}.{args.dev_bqdataset_name}.study_series` AS ss
  ON
    st.uuid = ss.study_uuid
  JOIN
    `{args.src_project}.{args.dev_bqdataset_name}.series` AS se
  ON
    ss.series_uuid = se.uuid
  JOIN
    `{args.src_project}.{args.dev_bqdataset_name}.series_instance` si
  ON
    se.uuid = si.series_uuid
  JOIN
    `{args.src_project}.{args.dev_bqdataset_name}.instance` i
  ON
    si.instance_uuid = i.uuid
  LEFT JOIN
    `{args.src_project}.{args.dev_bqdataset_name}.excluded_collections` ex
  ON
    c.collection_id = ex.tcia_api_collection_id
  JOIN
    collection_access
  ON
    c.idc_collection_id = collection_access.idc_collection_id
  LEFT JOIN
    license_info AS li
  ON
    se.source_doi = li.DOI AND se.source_url = li.URL
  WHERE
    ex.tcia_api_collection_id IS NULL 
  AND 
    i.excluded is False
  AND
    v.version = {args.version}
  ORDER BY
    tcia_api_collection_id, submitter_case_id, StudyInstanceUID, SeriesInstanceUID, SOPInstanceUID
"""


    client = bigquery.Client(project=args.dst_project)
    result=query_BQ(client, args.trg_bqdataset_name, args.bqtable_name, query, write_disposition='WRITE_TRUNCATE')
