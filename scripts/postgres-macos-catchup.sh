# when developing on macOS, you can use this script to setup PostgreSQL
# I have installed postgres.app and am using version 18

REMOTE_DIR=/root/r2lab-backups

TOPROOT=$(dirname $0)/..
cd $TOPROOT/former-data
echo in $PWD

echo "WARNING: you need to stop your local API server"
echo "before we can wipe the local r2lab database and restore it from the latest backup from the server"
echo -n "OK ? (Control-C to abort)"
read

retrieve the latest backup from the server, and restore it in a local r2lab database
latest=$(ssh r2labapi "ls $REMOTE_DIR/r2lab.*.pgdump | tail -n 1")
latestname=$(basename $latest)

echo "----- will use $latestname"
echo -n "OK ? (Control-C to abort) "
read

rsync -ai r2labapi:$latest .

echo "----- dropping and re-creating local 'r2lab' database"
echo -n "OK ? (Control-C to abort) "
read

dropdb --if-exists r2lab
createdb -O root r2lab
pg_restore --dbname=r2lab --format=custom --role root $latestname

echo "Done. You can now restart your local API server and test with the latest data from the server."
