#!/usr/bin/env bash

SCENARIO_REMOTE_URL_1="root@scenario-player.ci.raiden.network"
SCENARIO_REMOTE_URL_2="root@scenario-player2.ci.raiden.network"

### STYLES: IGNORE
COLUMNS=$(/usr/bin/tput cols)
RESET=$(/usr/bin/tput init)
BOLD=$(/usr/bin/tput bold)

function print_bold {
    echo -e "${BOLD}$1${RESET}"
}

function separator {
    printf '%*s\n' "${COLUMNS:-$(tput cols)}" '' | tr ' ' -
}
###

function display_usage {
    echo "This script does the following:"
    echo "1. Figures out the run number of each of the existing scenarios"
    echo "2. Downloads the logs for each of the nodes involved in the latest scenario run"
    echo "3. Looks through the logs and searches for errors / exceptions and reports them"
    echo -e "\n\nUSAGE: extract_sp_exceptions.sh [DESTINATION_DIR]\n"
    echo -e "Where\n"
    echo -e "\tDESTINATION_URL is optional and is used to specify the path prefix for the downloaded files. Otherwise the current directory is used\n"
}


if [[  $1 == "--help" ]]; then
    display_usage
    exit 1
fi

if [[ $1 != "" ]]; then
    DESTINATION_DIR=$1
else
    DESTINATION_DIR=$(pwd)
fi

DESTINATION_DIR="$(realpath -s "${DESTINATION_DIR}")/$(date +%m-%d-%Y)"
SCENARIOS_DIR="$DESTINATION_DIR"/scenarios

function download_service_logs {
    sources=()
    for file in "$@"; do
        sources+=("root@services-dev.raiden.network:/home/services/${file}")
    done

    scp "${sources[@]}" "${DESTINATION_DIR}"
}

function download_server_logs {
    current_server=$1

    (
        cd "${SCENARIOS_DIR}"

        ssh "$current_server" '
        cd /var/lib/scenario-player;
        source env.sh

        cd /data/scenario-player/scenarios;
        for scenario_path in "$SCENARIOS_DIR"/ci/"$SP"/*.yaml; do
            scenario_file=$(basename "$scenario_path")
            scenario=${scenario_file//.yaml}

            run=$(cat "${scenario}"/run_number.txt)

            find "$scenario"/node_"$run"_*
            ls "$scenario"/scenario-player-run* -1 -t | head -1
        done | tar zcf - -T -
        ' | tar zxf -
    )
}

function search_for_failures {
    mkdir -p "${DESTINATION_DIR}/errors/"
    echo -e "${BOLD}Looking for failures${RESET}"

    for scenario_logs in $(find "${SCENARIOS_DIR}" -maxdepth 2 -type f -name "scenario-player*.gz"); do
        scenario_successful=$(gunzip -c  "$scenario_logs" | jq 'select(.result == "success")')

        if [ -z "${scenario_successful}" ]; then
            scenario=$(basename "${scenario_logs}")
            scenario_dir=$(dirname "${scenario_logs}")

            separator
            print_bold "Scenario ${scenario} failed"
            gunzip -c  "$scenario_logs" | jq 'select(.result != null) | .message'
            separator

            for node_dir in $(find "${scenario_dir}" -maxdepth 1 -type d -name "node_*"); do
                gunzip -c ${node_dir}/*.log.gz | jq --tab 'select (.error!=null or .exception!=null)'
                cat "${node_dir}"/*.stderr | grep -v Starting | grep -v Stopped
            done

            separator

            gunzip -c "${scenario_dir}"/scenario-player-run_*.log.gz | jq 'select (.error!=null or .exception!=null)'
        fi
    done;
}

[ ! -d "$DESTINATION_DIR" ] && {
    mkdir -p "${SCENARIOS_DIR}"

    print_bold "Downloading services logs"
    download_service_logs ms-goerli-backup.gz ms-goerli.gz msrc-goerli-backup.gz msrc-goerli.gz pfs-goerli-with-fee.gz pfs-goerli.gz

    print_bold "Downloading scenarios list"
    download_server_logs $SCENARIO_REMOTE_URL_1
    download_server_logs $SCENARIO_REMOTE_URL_2
}

# search_for_failures expects the logs to be compressed
find "${SCENARIOS_DIR}" -type f -iname '*.log' | xargs gzip -q

search_for_failures
