import yaml

y = yaml.load(open('test.yaml', 'r'))

print yaml.dump(y)

print y['partitions'][0]['size']
print y['partitions'][2]['size']
for afile in y['partitions'][3]['files']:
    print afile

for number in y['partitions']['number']:
    print number
