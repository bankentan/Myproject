import time
with open("/tmp/ken", 'a+') as f:
  for i in range(1, 100):
    f.write(str(i)+'\n')
    print(i)
    time.sleep(0.1)

