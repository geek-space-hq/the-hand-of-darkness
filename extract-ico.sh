#!/bin/sh

faviconIcoPath="$(cat -)"
mostQualityIdentifier="$(identify "${faviconIcoPath}" | IFS=' ' awk '{print $3,$1}' | sort -t 'x' -k 1,1nr -k 2nr | head -n 1 | cut -d ' ' -f 2)"
exportFaviconPath="$(echo "${faviconIcoPath}" | sed 's/favicon.ico/favicon.png/g')"

convert "${mostQualityIdentifier}" -alpha on -background none "${exportFaviconPath}"

echo "${exportFaviconPath}"
