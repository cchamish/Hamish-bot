#!/bin/bash

#: Database report runner
#:
#: Arguments:
#:		1) The type of reports to run (e.g. daily, tri_weekly, weekly, weekly_python)
#:
#: Adopted from: Fastily

SCRIPT_DIR=$(dirname "$0")
REPORT_DIR=${SCRIPT_DIR}/reports
echo "Starting at: $(date -u '+%a %b %e %H:%M:%S %Y')"
##
# Runs a MySQL query against the labs replica database and puts the result in ~/public_html/r.
#
# Arguments:
#	1) The database to use (e.g. 'enwiki', 'commonswiki')
#	2) Path(s) to the sql file(s) to execute
##
do_query() {
        case ${1} in
            commonswiki)
                SQL_QUERY="SELECT page.page_title FROM page WHERE page.page_namespace=6;"
                ;;
            zhwiki)
                SQL_QUERY="SELECT wpg.page_title FROM zhwiki_p.page wpg LEFT JOIN zhwiki_p.image wpimg ON wpimg.img_name = wpg.page_title WHERE wpg.page_namespace=6 AND wpimg.img_name IS null;"
                ;;
            *)
                echo "Unknown query name: ${1}"
                ;;
        esac

        # Run the query and save the result
        echo "Executing query for ${1}..."
        : > "${REPORT_DIR}/${1}.txt"
        mysql --defaults-file=~/replica.my.cnf -q -r -B -N -h "${1}.analytics.db.svc.wikimedia.cloud" "${1}_p" -e "$SQL_QUERY" > "${REPORT_DIR}/${1}.txt"
    echo "Completed query execution for ${1}"
}

##
# Get the intersection of two sorted reports and save the result in ~/public_html/r.
#
# Arguments:
#	1) The id of the first file to use.  This should be the smaller file (it will be loaded into memory)
#	2) The id of the second file to use.  This should be the larger file
#	3) The output file id
##
intersection() {
    echo "Line count in ${REPORT_DIR}/${1}.txt: $(wc -l < "${REPORT_DIR}/${1}.txt")"
    echo "Line count in ${REPORT_DIR}/${2}.txt: $(wc -l < "${REPORT_DIR}/${2}.txt")"
    awk 'NR==FNR { lines[$0]=1; next } $0 in lines' "${REPORT_DIR}/${1}.txt" "${REPORT_DIR}/${2}.txt" > "${REPORT_DIR}/${3}.txt"
    echo "Line count in ${REPORT_DIR}/${3}.txt: $(wc -l < "${REPORT_DIR}/${3}.txt")"
}

case "$1" in
    report)
        mkdir -p "$REPORT_DIR"
        echo $SCRIPT_DIR
        echo $REPORT_DIR
        do_query commonswiki
        do_query zhwiki
        intersection zhwiki commonswiki report1
        echo "Completed report generation"
        ;;
    *)
        printf "Not a known argument: %s\n\n" "$1"
        ;;
esac