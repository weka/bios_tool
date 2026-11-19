#!/bin/bash
#
# Builds bios_tool as one binary with PyInstaller, and a tarball of it with the settings files, so it can be
# deployed without Python. Every file is taken as committed, never from the working tree, so a host list holding
# real BMC passwords cannot end up in the tarball.
#
set -euo pipefail
cd "$( dirname "$0" )"

TOOL=bios_tool
TARGET=tarball/${TOOL}
FILES="bios_settings.yml WEKApod.yml Dell-Genoa-bios.yml defaults-db.yml host_config.csv README.md"

pyinstaller --onefile "${TOOL}.py"

rm -rf "${TARGET}"
mkdir -p "${TARGET}"
cp "dist/${TOOL}" "${TARGET}/"
for file in ${FILES}
do
  git show "HEAD:${file}" > "${TARGET}/${file}"
done

tar -C tarball -czf "${TOOL}.tar.gz" "${TOOL}"
echo "built ${TOOL}.tar.gz from $( git describe --always --dirty )"
