# This is a simple simulation of the peer connections a BitTorrent swarm.
# it attempts to illustrate the problem of clustering when connections
# are long lived under "perfect" conditions. Perfect meaning nobody is behind
# NAT and every peer can connect to everybody else and every peer has the
# same connection limit settings and the same first-come-first-serve
# logic for accepting connections.
# 
# The fix to mitigate this clustering is to use peer-ordering. A scheme
# where each pair of peers has a global rank, or priority. Each peer
# prioritizes its connections based on this rank, in order to create a
# more uniformly connected graph.
# 
# This program requires that you have 'dot' installed on your system.
# or more specifically, 'graphviz'.
# 
#TODO: simulate proper peer-exchange 
#TODO: make the settings configurable from the command line

import hashlib
import random
import os
import math

# ======= settings ==========

# this is the max number of peer connections each peer has
max_peers = 10

# this is the number of peers the tracker responds with
peers_from_tracker = 40

# this is the number of connection attempts each peer can
# have outstanding at any given time (it's also limited
# by max_peers)
half_open_limit = 10

# peer ordering turns on and off the global connection ranking
use_peer_ordering = True
#use_peer_ordering = False

# global knowledge is a simplification of taking DHT and PEX into
# account. When enabled, every peer magically knows about every
# other peer. When disabled, peers only know about a subset of
# peers that existed by the time they joined the swarm, and peers
# that have attempted to connect to them
use_global_knowledge = True

# this is the target number of peers in the swarm. Each simulation
# tick introduces one more peer. This also indirectly determines
# the length of the simulation run, which is 150% of this setting
swarm_size = 50

# set this to 0 to supress debug logging, set to 2 to make it
# more verbose
logging = 0

# ======= global state ==========

# global tick counter
tick = 0

peers_in_swarm = set()

# map node -> [node, ...]
# the nodes each node is connected to
est_connections = {}

# map node -> [node, ...]
# the nodes each node is currently trying to connect to
connection_attempts = {}

# map node -> [node, ...]
# the nodes each node knows about, but are not connected to
known_peers = {}

# number of connection attempts per tick, used for graphing
attempts_per_tick = []

# number of connection attempts being rejected each tick
rejects_per_tick = []

# number of established connections being replaced each tick
# (because of a higher ranking peer connecting)
replacements_per_tick = []

# maps node -> tick counter when that node was added to the swarm
join_time = {}

# this is a list of lists of integers. Each element in the
# outermost list represents the state for all peers n ticks
# from when they joined the swarm. Each state is a list of
# the number of peers each peer has been able to connect to.
# we keep all the numbers so that we can extract percentiles
# out of it. This is an indication of the startup time or
# time it takes to join the swarm. The first 'max_peers' nodes
# are ignored because their join time is limited by the rate
# at which new peers join the swarm, not how well they can
# connect to other peers
startup = []

# this is the global priority function of connections/node pairs
def prio(n1, n2):
	if n1 > n2:
		t = n2
		n2 = n1
		n1 = t

	h = hashlib.sha1()
	h.update('%d%d' % (n1, n2))
	return h.hexdigest()

# give node 'n' a chance to try to connect to some peers (if it
# isn't fully connected already)
def maybe_connect_more_peers(n):
	# initialize our state if it isn't already
	if not n in est_connections: est_connections[n] = []
	if not n in connection_attempts: connection_attempts[n] = []

	if len(est_connections[n]) + len(connection_attempts[n]) >= max_peers:
		return

	# if global knowledge is enabled, always update the known peers list
	# from the global peer list (filtering out peers we're already connected
	# to, connecting to and ourself)
	if use_global_knowledge:
		known_peers[n] = filter(lambda x: x != n and not x in connection_attempts[n] and not x in est_connections[n], list(peers_in_swarm))

	# if we're using peer priorities
	# order the peers we got based on
	# their priority, otherwise shuffle the peers
	if use_peer_ordering:
		known_peers[n].sort(key = lambda x: prio(n, x), reverse = True)
	else:
		random.shuffle(known_peers[n])

	while len(est_connections[n]) + len(connection_attempts[n]) < max_peers \
		and len(connection_attempts[n]) < half_open_limit \
		and len(known_peers[n]) > 0:
		connection_attempts[n].append(known_peers[n].pop(0))

		attempts_per_tick[tick] += 1

# add peer 'n' to the swarm
def add_new_peer(n):
	# get peers from tracker

	peers = list(peers_in_swarm)
	random.shuffle(peers)
	peers = peers[0:peers_from_tracker]
	known_peers[n] = peers
	if logging > 1:
		print 'adding peer "%d", tracker: ', peers

	peers_in_swarm.add(n)
	join_time[n] = tick

	maybe_connect_more_peers(n)

# take one step in the simulation
def step():
	print '==== TICK: %-4d ===' % tick
	rejects_per_tick.append(0)
	replacements_per_tick.append(0)
	attempts_per_tick.append(0)

	# resolve connection attempts
	for n in peers_in_swarm:
		for a in list(connection_attempts[n]):
			# n is trying to connect to a
			if not a in est_connections: est_connections[a] = []
			if not n in est_connections: est_connections[n] = []
			if logging > 1:
				print '%d connecting to %d' % (n, a)
			if not n in known_peers[a] \
				and not n in est_connections[a] \
				and not n in connection_attempts[a]:
				known_peers[a].append(n)

			if logging > 1:
				print '%d knows about %d' % (a, n)
			connections = sorted(est_connections[a], key = lambda x: prio(n, x))
			if logging > 1:
				print '%d has connections: ' % (a), connections

			if a in est_connections[n]:
				# we're already connected! This may happen when two
				# peers connect to each other simultaneously
				# don't do anything, just let the attempt be removed
				pass
			elif len(connections) < max_peers:
				#connection attempt succeeded!
				est_connections[a].append(n)
				est_connections[n].append(a)
				if logging > 0:
					print 'establishing %d - %d' % (n, a)
			elif use_peer_ordering and prio(connections[0], a) < prio(n, a):
				#connection attempt succeeded!
				#by replacing a lower ranking one
				if logging > 0:
					print 'replacing %d - %d [%s] with %d - %d [%s]' % (connections[0], a, prio(connections[0], a), n, a, prio(n, a))
				est_connections[connections[0]].remove(a)
				est_connections[a].remove(connections[0])
				known_peers[a].append(connections[0])
				known_peers[connections[0]].append(a)
				est_connections[a].append(n)
				est_connections[n].append(a)

				replacements_per_tick[tick] += 1

			else:
				# connection attempt rejected
				rejects_per_tick[tick] += 1

			try: known_peers[a].remove(n)
			except: pass
			try: known_peers[n].remove(a)
			except: pass
			connection_attempts[n].remove(a)

		# track ramp-up time for peers
		if n >= max_peers:
			node_time = tick - join_time[n]
			while len(startup) <= node_time: startup.append([])
			startup[node_time].append(len(est_connections[n]))

	for n in peers_in_swarm:
		maybe_connect_more_peers(n)

def render():
	global tick
	f = open('dots/frame%d.dot' % tick, 'w+')

	print >>f, 'graph swarm {'

	printed_conns = set()
	for n,conns in est_connections.iteritems():
		# print nodes
		print >>f, '"%d";' % n

		# print edges (connections)
		for c in conns:
			if (c, n) in printed_conns: continue
			print >>f, '"%d" -- "%d" [splines=true];' % (n, c)
			printed_conns.add((n, c))

	for n,conns in connection_attempts.iteritems():
		for c in conns:
			print >>f, '"%d" -- "%d" [dirType="forward", color=red, constraint=false, style=dotted, weight=0];' % (n, c)

	print >>f, '}'
	f.close()

	os.system('sfdp -oframes/frame%d.png -Tpng dots/frame%d.dot &' % (tick, tick))

	histogram = {}
	for n,conns in est_connections.iteritems():
		rank = len(conns)
		if not rank in histogram: histogram[rank] = 1
		else: histogram[rank] += 1

	f = open('dots/frame%d.dat' % tick, 'w+')
	for i,n in histogram.iteritems():
		print >>f, '%d %d' % (i, n)
	f.close();

	f = open('dots/render_rank_histogram%d.gnuplot' % tick, 'w+')
	print >>f, 'set term png size 600,300'
	print >>f, 'set output "plots/frame%d.png"' % tick
	print >>f, 'set ylabel "number of peers"'
	print >>f, 'set xlabel "number of connections"'
	print >>f, 'set style fill solid'
	print >>f, 'set xrange [0:%d]' % (max_peers + 1)
	print >>f, 'set yrange [0:*]'
	print >>f, 'set boxwidth 1'
	print >>f, 'plot "dots/frame%d.dat" using 1:2 with boxes' % tick
	f.close()

	os.system('gnuplot dots/render_rank_histogram%d.gnuplot &' % tick)

def plot_list(samples, name):
	f = open('dots/%s.dat' % name, 'w+')
	counter = 0
	for i in samples:
		print >>f, '%d %d' % (counter, i)
		counter += 1
	f.close();

	f = open('dots/render_%s.gnuplot' % name, 'w+')
	print >>f, 'set term png size 800,300'
	print >>f, 'set output "%s.png"' % name
	print >>f, 'set ylabel "%s"' % name
	print >>f, 'set xlabel "tick"'
	print >>f, 'set yrange [0:*]'
	print >>f, 'plot "dots/%s.dat" using 1:2 with steps' % name
	f.close()

	os.system('gnuplot dots/render_%s.gnuplot &' % name)

# from: https://code.activestate.com/recipes/511478-finding-the-percentile-of-the-values/
def percentile(N, percent, key=lambda x:x):
	"""
	Find the percentile of a list of values.

	@parameter N - is a list of values. Note N MUST BE already sorted.
	@parameter percent - a float value from 0.0 to 1.0.
	@parameter key - optional key function to compute value from each element of N.

	@return - the percentile of the values
	"""
	if not N:
		return None
	k = (len(N)-1) * percent
	f = math.floor(k)
	c = math.ceil(k)
	if f == c:
		return key(N[int(k)])
	d0 = key(N[int(f)]) * (c-k)
	d1 = key(N[int(c)]) * (k-f)
	return d0+d1

def plot_percentiles(samples, name):

	f = open('dots/%s.dat' % name, 'w+')
	counter = 0
	for i in samples:
		i.sort()
		if i == []: i.append(0)
		# print 10th 90th, 20th, 80th, 30th, 70th, 40th, 60th and 50th percentiles
		print >>f, '%d %d %d %d %d %d %d %d %d %d' \
			% (counter, percentile(i, 0.10), percentile(i, 0.90), percentile(i, 0.2), percentile(i, 0.8), percentile(i, 0.3), percentile(i, 0.7), percentile(i, 0.4), percentile(i, 0.6), percentile(i, 0.5))
		print 'min: %d max: %d' % (min(i), max(i))
		if min(i) > 0 and min(i) == max(i): break
		counter += 1
	f.close();

	f = open('dots/render_%s.gnuplot' % name, 'w+')
	print >>f, 'set term png size 800,300'
	print >>f, 'set output "%s.png"' % name
	print >>f, 'set ylabel "%s"' % name
	print >>f, 'set xlabel "tick"'
	print >>f, 'set key right bottom'
	print >>f, 'plot "dots/%s.dat" using 1:2:3 with filledcurves closed title "10th-90th percentile" lc rgb "#ffdddd",' % name,
	print >>f, '"dots/%s.dat" using 1:4:5 with filledcurves closed title "20th-80th percentile" lc rgb "#ffbbbb",' % name,
	print >>f, '"dots/%s.dat" using 1:6:7 with filledcurves closed title "30th-70th percentile" lc rgb "#ff9999",' % name,
	print >>f, '"dots/%s.dat" using 1:8:9 with filledcurves closed title "40th-60th percentile" lc rgb "#ff7777",' % name,
	print >>f, '"dots/%s.dat" using 1:10 with lines title "median" lc rgb "#cc5555"' % name,
	f.close()

	os.system('gnuplot dots/render_%s.gnuplot &' % name)


## main program ##


try: os.mkdir('plots')
except: pass
try: os.mkdir('dots')
except: pass
try: os.mkdir('frames')
except: pass

for i in xrange(0, int(swarm_size * 3)):

	step()

	# add a new peer every other tick
	if len(peers_in_swarm) < swarm_size and i % 2 == 0:
		add_new_peer(len(peers_in_swarm))

	render()

	tick += 1

plot_list(attempts_per_tick, 'connection_attempts')
plot_list(rejects_per_tick, 'connection_rejects')
plot_list(replacements_per_tick, 'connection_replacements')
plot_percentiles(startup, 'peer_startup')

