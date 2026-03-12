# when developing on macOS, you can use this script to setup PostgreSQL
# I have installed postgres.app and am using version 18


TOPROOT=$(dirname $0)/..
cd $TOPROOT/former-data
echo in $PWD


# (1) to re-create the planetlab5 database from a more recent dump

latest=$(ls -1 planetlab5.*.sql | tail -n 1)
echo -n "latest backup is $latest; OK ? (Control-C to abort) "
read
# DATE=$(echo $latest | cut -d. -f2)
# echo restoring planetlab5 from backup $DATE

# rsync -ai r2labapi:/var/lib/pgsql/backups/planetlab5.$DATE.sql .

dropdb planetlab5
createdb planetlab5
psql -U postgres -d planetlab5 < $latest

echo You should now re-run the migration script to produce the initial state of the r2lab database
