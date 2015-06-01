#!/bin/bash

export DISK_SIZE=8G #100M #8G
export PARTITION_FILE='rocketboard/partitions'
export PYTHONPATH=`pwd`
#export 
python morphlib/exts/rawdisk.write $1 testnew.img
