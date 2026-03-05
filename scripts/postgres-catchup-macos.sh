# when developing on macOS, you can use this script to setup PostgreSQL
# I have installed postgres.app and am using version 18


TOPROOT=$(dirname $0)/..
cd $TOPROOT/former-data
echo in $PWD


# (1) to re-create the planetlab5 database from a more recent dump

DATE=2026-03-05-12-19-05
echo restoring planetlab5 from backup $DATE

rsync -ai r2labapi:/var/lib/pgsql/backups/planetlab5.$DATE.sql .

dropdb planetlab5
createdb planetlab5
psql -U postgres -d planetlab5 < planetlab5.$DATE.sql

echo You should now re-run the migration script to produce the initial state of the r2lab database
