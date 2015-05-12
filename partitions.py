import yaml
import re
import subprocess
import cliapp

import sys
import os
import stat

recognised_filesystem_formats = ['btrfs', 'ext4', 'vfat']

def load_partition_data():
    with open('test.yaml', 'r') as f:
         partspec = yaml.load(f)
    return partspec

###############################################################################

def check_partition_info(partition):
    print partition['la']
    print "no la"

## Verify
#try:
#    seen = set()
#    numberofparts = 0
#    for partition in partitions:
#        partnum = partition['number']
#        self.check_partition_info(partition)
#        if partnum in seen:
#            raise
#        else:
#            seen.add(partnum)
#        if partnum > numberofparts:
#            numberofparts = partnum
#except BaseException:
#    print "Duplicated partition numbers"


###############################################################################

def _parse_size(size):
    '''Parse a size from a string.

    Return size in bytes.

    '''

    m = re.match('^(\d+)([kmgKMG]?)$', size)
    if not m:
        return None

    factors = {
        '': 1,
        'k': 1024,
        'm': 1024**2,
        'g': 1024**3,
    }
    factor = factors[m.group(2).lower()]

    return int(m.group(1)) * factor

def get_boolean(string):
    string = str(string).lower()
    if string in ['no', '0', 'false']:
        return False
    elif string in ['yes', '1', 'true']:
        return True
    else:
        raise cliapp.AppException('Unexpected value %s' %
                                  string)

def is_device(location):
    try:
        st = os.stat(location)
        return stat.S_ISBLK(st.st_mode)
    except OSError as e:
        if e.errno == errno.ENOENT:
            return False
        raise

###############################################################################


size = _parse_size('6G')

def process_partition_data(partition_data):
    ''' Update offsets (sectors) and sizes (bytes) for each partition '''
    total_size = 0
    partitions = partition_data['partitions']
    offset = partition_data['start_offset']
    part_num = 1
    for partition in partitions:
        size_bytes = _parse_size(str(partition['size'])) 
        total_size += size_bytes
        size_sectors = (size_bytes / 512 +
                      ((size_bytes % 512) != 0) * 1)
        partition['size_sectors'] = size_sectors
        partition['start'] = offset
        partition['end'] = offset + size_sectors
        offset += size_sectors + 1

        if 'boot' in partition.keys():
            partition['boot'] = get_boolean(partition['boot'])
        else:
            partition['boot'] = False

        partition['number'] = part_num
        part_num += 1

        print 'Number:   ' + str(partition['number'])
        print '  Start:  ' + str(partition['start'])
        print '  End:    ' + str(partition['end'])
        print '  Ftype:  ' + str(partition['fdisk_type'])
        print '  Format: ' + str(partition['format'])
        print '  Size:   ' + str(partition['size'])

    # Compare with DISK_SIZE
    print total_size
    if total_size > size: # TODO
        print "Requested size exceeds disk image size"

def process_validate_partitions():
    print "TODO"
    # Check duplicated fill
    # Check duplicated rootfs (an at least one)
    # fdisk_type, format, and size are mandatory
    # Maximum 4 partitions
    # invalid filesystem types, default is none


location = 'test.img'
# image must already exist
def create_partition_table(location, partition_data):

    print "Creating partition table"

    partitions = partition_data['partitions']
    p = subprocess.Popen(["fdisk", location],
                         stdin=subprocess.PIPE,
#                         stdout=sys.stdout, stderr=sys.stdout)
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    # Create a new partition table
    p.stdin.write("o\n")
    for partition in partitions:
        part_num = partition['number']
        # Create partitions
        if partition['fdisk_type'] != 'none':
            cmd = ("n\n"
                   "p\n"
                   "" + str(part_num) + "\n"
                   "" + str(partition['start']) + "\n"
                   "" + str(partition['end']) + "\n")
            p.stdin.write(cmd)

            # Set partition types
            cmd = "t\n"
            if part_num > 1:
                # fdisk does not ask for a partition
                # number when setting the type of the
                # first created partition
                cmd += str(part_num) + "\n"
            cmd += str(partition['fdisk_type']) + "\n"
            p.stdin.write(cmd)

            # Set boot flag
            if partition['boot']:
                cmd = "a\n"
                if part_num > 1:
                    cmd += str(part_num) + "\n"
                p.stdin.write(cmd)

    # TODO Catch invalid partition types, etc

    # Write changes
    cmd = ("w\n"
           "q\n")
    p.stdin.write(cmd)
    p.wait()

    # Probe for new partitions (required?)
    p = subprocess.Popen(["partprobe"])

def mount_partition(partition_data, part_num):
    return True

def create_loopback(location, offset):
    try:
        device = cliapp.runcmd(['losetup', '--show', '-f',
                                '-o', str(offset), location])
        cliapp.runcmd(['partprobe'])

        return device.rstrip()
    except BaseException:
        print "Error creating loopback"

def detach_loopback(loop_device):
    try:
        out = cliapp.runcmd(['losetup', '-d', loop_device])
    except BaseException:
        print "Error detaching loopback"

# For all operations

def create_partition_filesystems(location, partition_data):
   
    print "Creating filesystems"
    partitions = partition_data['partitions']

    for partition in partitions:
        filesystem = partition['format']
        if filesystem != 'none':
            if is_device(location):
                device = location + partition['number']
                loop = False
            else:
                device = create_loopback(location, partition['start'])
                loop = True

            if filesystem == 'btrfs':
                #self.format_btrfs(device)
                print "TODO: make a btrfs filesystem"
            elif filesystem in recognised_filesystem_formats:
                # Do this in verification?
                cliapp.runcmd(['mkfs.' + filesystem, device])
            else:
                raise cliapp.AppException('Unrecognised filesystem format')

            if loop:
                detach_loopback(device)

def copy_partition_files():
    print 'TODO'

def copy_files():
    print 'TODO'


# raw file offsets

#def direct_write_file():

# Self function references

# default one partition partition map

# USE_PARTITIONING=yes
# PARTITION_MAP=file

partition_data = load_partition_data()
#print partition_data
process_partition_data(partition_data)
#print partition_data
create_partition_table(location, partition_data)
create_partition_filesystems(location, partition_data)
print partition_data

def paramtest(one, two, three=0):
    print one
    print two
    print three

paramtest('a','b','c')
paramtest('a','b')

#            for line in iter(p.stdout.readline, ''):
#                line = line.replace('\r', '').replace('\n', '')
#                print line
