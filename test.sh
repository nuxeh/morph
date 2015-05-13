#!/bin/bash

export DISK_SIZE=3G
export PARTITION_FILE='rocketboard/partitions'
export PYTHONPATH=`pwd`
python morphlib/exts/rawdisk.write temproot testnew.img
