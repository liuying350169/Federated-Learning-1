

Time_start = 1540196479.93

fi = open("timeline_server.txt", "r")

fo = open("time_server.txt", "w")

for line in fi:
	lis = line.split("    ")
	time = float(lis[2])
	time -= Time_start
	lis[2] = str(time)
	fo.write(lis[0] + "    " + lis[1] + "    " + lis[2] + "\n")

fo.close()

fi.close()
