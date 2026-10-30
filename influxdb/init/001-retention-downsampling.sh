#!/bin/sh
set -e

DB="${INFLUXDB_DB}"
MEAS="${INFLUX_MEASUREMENT:-kostal_plenticore}"

influx -username "${INFLUXDB_ADMIN_USER}" -password "${INFLUXDB_ADMIN_PASSWORD}" -execute \
  "ALTER RETENTION POLICY \"autogen\" ON \"${DB}\" DURATION 1d REPLICATION 1 SHARD DURATION 1h DEFAULT"

influx -username "${INFLUXDB_ADMIN_USER}" -password "${INFLUXDB_ADMIN_PASSWORD}" -execute \
  "CREATE RETENTION POLICY \"rp_1min\" ON \"${DB}\" DURATION 7d REPLICATION 1"

influx -username "${INFLUXDB_ADMIN_USER}" -password "${INFLUXDB_ADMIN_PASSWORD}" -execute \
  "CREATE RETENTION POLICY \"rp_5min\" ON \"${DB}\" DURATION 0s REPLICATION 1"

influx -username "${INFLUXDB_ADMIN_USER}" -password "${INFLUXDB_ADMIN_PASSWORD}" -execute \
  "CREATE CONTINUOUS QUERY \"cq_1min\" ON \"${DB}\" RESAMPLE EVERY 1m FOR 2m BEGIN SELECT mean(\"value\") AS \"value\", mean(\"value_int\") AS \"value_int\", last(\"value_bool\") AS \"value_bool\", last(\"value_str\") AS \"value_str\" INTO \"${DB}\".\"rp_1min\".\"${MEAS}\" FROM \"${DB}\".\"autogen\".\"${MEAS}\" GROUP BY time(1m), \"source\", \"model\", \"point\", \"unit\" END"

influx -username "${INFLUXDB_ADMIN_USER}" -password "${INFLUXDB_ADMIN_PASSWORD}" -execute \
  "CREATE CONTINUOUS QUERY \"cq_5min\" ON \"${DB}\" RESAMPLE EVERY 5m FOR 10m BEGIN SELECT mean(\"value\") AS \"value\", mean(\"value_int\") AS \"value_int\", last(\"value_bool\") AS \"value_bool\", last(\"value_str\") AS \"value_str\" INTO \"${DB}\".\"rp_5min\".\"${MEAS}\" FROM \"${DB}\".\"rp_1min\".\"${MEAS}\" GROUP BY time(5m), \"source\", \"model\", \"point\", \"unit\" END"
