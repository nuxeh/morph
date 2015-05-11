import yaml
import re
import subprocess

valid_filesystem_formats = ['btrfs', 'ext4', 'vfat']

def load_partition_data():
    with open('test.yaml', 'r') as f:
         partspec = yaml.load(f)
    #start_offset = partspec['start offset']
    return partspec

    print start_offset

    print yaml.dump(partspec)

    print partspec['partitions'][0]['size']
    print partspec['partitions'][2]['size']
    for afile in partspec['partitions'][3]['files']:
        print afile

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

def get_boolean(self, value)
    if value in ['no', '0', 'false']:
        return False
    elif value in ['yes', '1', 'true']:
        return True
    else:
        raise cliapp.AppException('Unexpected value for %s: %s' %
                                  (variable, value))

###############################################################################

size = _parse_size('6G')

def process_partition_offsets(partition_data):
    ''' Update offsets (sectors) and sizes (bytes) for each partition '''
    total_size = 0
    partitions = partition_data['partitions']
    offset = partition_data['start offset']
    for partition in partitions:
        size_bytes = _parse_size(str(partition['size'])) 
        partition['size'] = size_bytes 
        total_size += size_bytes
        size_sectors = (size_bytes / 512 +
                      ((size_bytes % 512) != 0) * 1)
        partition['size_sectors'] = size_sectors
        partition['start'] = offset
        print "start: " + str(partition['start'])
        partition['end'] = offset + size_sectors
        print "end: " + str(partition['end'])
        offset += size_sectors + 1

    # Compare with DISK_SIZE
    print total_size
    if total_size > size:
        print "Requested size exceeds disk image size"

    print total_size
    print partitions


def process_validate_partitions():
    print "TODO"


#except BaseException:
#    print "error"

location = 'test.img'

def create_partition_table(location, partition_data):

    out_file = open("out_file", 'w')
    partitions = partition_data['partitions']
    p = subprocess.Popen(["fdisk", location],
                         stdin=subprocess.PIPE,
                         stdout=out_file, stderr=subprocess.PIPE)
#                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    part_num = 1
    # Create a new partition table
    p.stdin.write("o\n")
    for partition in partitions:
        # Create partitions
        if partition['type'] != 'none':
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
            cmd += str(partition['type']) + "\n"
            p.stdin.write(cmd)

            # Set boot flag
            if partition['boot']:
                cmd = ("a\n"
                if part_num > 1:
                    cmd += partnum + "\n"
                p.stdin.write(cmd)
        part_num += 1

    # TODO Catch invalid partition types, etc

    # Write changes
    cmd = ("w\n"
           "q\n")
    p.stdin.write(cmd)
    #p.wait()

#    if p.returncode != 0:
    # Probe for new partitions (required?)
    p = subprocess.Popen(["partprobe"])
    p.wait()
    if p.returncode != 0:
        print "error: could not reload the partition table from image"

def mount_partition(partition_data, part_num):
    return device

def create_loopback():
    return device

def remove_loopback():

def create_partition_filesystems(partition_data):
    

def copy_files():

def direct_write_file():


# USE_PARTITIONING=yes
# PARTITION_MAP=file

partition_data = load_partition_data()
process_partition_offsets(partition_data)
create_partition_table(location, partition_data)




#            for line in iter(p.stdout.readline, ''):
#                line = line.replace('\r', '').replace('\n', '')
#                print line
