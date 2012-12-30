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
#TODO: profile and optimize

import hashlib
import random
import os
import math
import argparse

parser = argparse.ArgumentParser(description='simulate connectivity in a bittorrent swarm')

# ======= settings ==========

# this is the max number of peer connections each peer has
parser.add_argument('--max-peers', dest='max_peers', default=10, type=int, help='the max number of connections each peer can have')

# this is the target number of peers in the swarm. Each simulation
# tick introduces one more peer. This also indirectly determines
# the length of the simulation run, which is 150% of this setting
parser.add_argument('--swarm-size', dest='swarm_size', default=100, type=int, help='the total size of the swarm to simulate')

# this is the number of peers the tracker responds with
parser.add_argument('--peers-from-tracker', dest='peers_from_tracker', default=40, type=int, help='the number of peers returned from the tracker')

# this is the number of connection attempts each peer can
# have outstanding at any given time (it's also limited
# by max_peers)
parser.add_argument('--half-open-limit', dest='half_open_limit', default=10, type=int, help='the max number of outstanding connection attempts per peer')

# peer ordering turns on and off the global connection ranking
parser.add_argument('--no-peer-ordering', dest='use_peer_ordering', default=True, action='store_const', const=False, help='disable global peer ranking in accepting connections')

# global knowledge is a simplification of taking DHT and PEX into
# account. When enabled, every peer magically knows about every
# other peer. When disabled, peers only know about a subset of
# peers that existed by the time they joined the swarm, and peers
# that have attempted to connect to them
parser.add_argument('--no-global-knowledge', dest='use_global_knowledge', default=True, action='store_const', const=False, \
	help='disable global knowledge of all peers (makes peers only know about a subset of the other peers)')

# disable rendering the dot graphs for each step
parser.add_argument('--no-graph-plot', dest='plot_graph', default=True, action='store_const', const=False, help='disable rendering the graph for each step')

# render node rank histogram for each step
parser.add_argument('--plot-rank-histogram', dest='plot_rank_histogram', default=False, action='store_const', const=True, help='render a histogram of node rank for each step')

# set this to 0 to supress debug logging, set to 2 to make it
# more verbose
parser.add_argument('--logging', dest='logging', default=0, type=int, help='enable logging (1=moderate logging 2=verbose logging)')

settings = parser.parse_args()

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
# time it takes to join the swarm. The first 'settings.max_peers' nodes
# are ignored because their join time is limited by the rate
# at which new peers join the swarm, not how well they can
# connect to other peers
startup = []

# a cache of connection priority
# maps (node, node) -> priority
prio_cache = {}

# this is the global priority function of connections/node pairs
def prio(n1, n2):
	if n1 > n2:
		t = n2
		n2 = n1
		n1 = t

	if (n1, n2) in prio_cache: return prio_cache[(n1, n2)]

	h = hashlib.sha1()
	h.update('%d%d' % (n1, n2))
	p = h.hexdigest()
	prio_cache[(n1, n2)] = p
	return p

# give node 'n' a chance to try to connect to some peers (if it
# isn't fully connected already)
def maybe_connect_more_peers(n):
	# initialize our state if it isn't already
	if not n in est_connections: est_connections[n] = []
	if not n in connection_attempts: connection_attempts[n] = []

	if len(est_connections[n]) + len(connection_attempts[n]) >= settings.max_peers:
		return

	# if global knowledge is enabled, always update the known peers list
	# from the global peer list (filtering out peers we're already connected
	# to, connecting to and ourself)
#	if settings.use_global_knowledge:
#		known_peers[n] = filter(lambda x: x != n and not x in connection_attempts[n] and not x in est_connections[n], list(peers_in_swarm))

	# if we're using peer priorities
	# order the peers we got based on
	# their priority, otherwise shuffle the peers
	if not settings.use_peer_ordering:
		random.shuffle(known_peers[n])

	while len(est_connections[n]) + len(connection_attempts[n]) < settings.max_peers \
		and len(connection_attempts[n]) < settings.half_open_limit \
		and len(known_peers[n]) > 0:

		if settings.use_peer_ordering:
			peer = max(known_peers[n], key = lambda x: prio(n, x))
			known_peers[n].remove(peer)
		else:
			peer = known_peers[n].pop(random.randint(0, len(known_peers[n])-1))

		connection_attempts[n].append(peer)

		attempts_per_tick[tick] += 1

# add peer 'n' to the swarm
def add_new_peer(n):

	if settings.use_global_knowledge:
		# if using global knowledge, this new peer
		# instantly knows about everyone else
		known_peers[n] = list(peers_in_swarm)

		# if all peers have global knowlegde, tell everybody
		# about this new peer
		for p in peers_in_swarm:
			known_peers[p].append(n)
	else:
		# get peers from tracker
		peers = list(peers_in_swarm)
		random.shuffle(peers)
		peers = peers[0:settings.peers_from_tracker]
		known_peers[n] = peers

	if settings.logging > 1:
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
			if settings.logging > 1:
				print '%d connecting to %d' % (n, a)
			if not n in known_peers[a] \
				and not n in est_connections[a] \
				and not n in connection_attempts[a]:
				known_peers[a].append(n)

			if settings.logging > 1:
				print '%d knows about %d' % (a, n)
			connections = est_connections[a]
			if settings.logging > 1:
				print '%d has connections: ' % (a), connections

			if len(connections) > 0:
				lowest_rank_connection = connections[0]
				if settings.use_peer_ordering:
					lowest_rank_connection = min(connections, key = lambda x: prio(n, x))

			established = True
			if a in est_connections[n]:
				# we're already connected! This may happen when two
				# peers connect to each other simultaneously
				# don't do anything, just let the attempt be removed
				pass
			elif len(connections) < settings.max_peers:
				#connection attempt succeeded!
				est_connections[a].append(n)
				est_connections[n].append(a)
				if settings.logging > 0:
					print 'establishing %d - %d' % (n, a)
			elif settings.use_peer_ordering and prio(lowest_rank_connection, a) < prio(n, a):
				#connection attempt succeeded!
				#by replacing a lower ranking one
				if settings.logging > 0:
					print 'replacing %d - %d [%s] with %d - %d [%s]' % (lowest_rank_connection, a, prio(lowest_rank_connection, a), n, a, prio(n, a))
				est_connections[lowest_rank_connection].remove(a)
				est_connections[a].remove(lowest_rank_connection)
				known_peers[a].append(lowest_rank_connection)
				known_peers[lowest_rank_connection].append(a)

				est_connections[a].append(n)
				est_connections[n].append(a)

				replacements_per_tick[tick] += 1

			else:
				# connection attempt rejected
				established = False
				rejects_per_tick[tick] += 1
				known_peers[n].append(a)

			if established:
				try: known_peers[a].remove(n)
				except: pass
				try: known_peers[n].remove(a)
				except: pass

			connection_attempts[n].remove(a)

		# track ramp-up time for peers
		if n >= settings.max_peers:
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

	if settings.plot_graph:
		os.system('sfdp -oframes/frame%d.png -Tpng dots/frame%d.dot &' % (tick, tick))

	histogram = {}
	for n,conns in est_connections.iteritems():
		rank = len(conns)
		if not rank in histogram: histogram[rank] = 1
		else: histogram[rank] += 1

	f = open('dots/frame%d.txt' % tick, 'w+')
	for i,n in histogram.iteritems():
		print >>f, '%d %d' % (i, n)
	f.close();

	f = open('dots/render_rank_histogram%d.gnuplot' % tick, 'w+')
	print >>f, 'set term png size 600,300'
	print >>f, 'set output "plots/frame%d.png"' % tick
	print >>f, 'set ylabel "number of peers"'
	print >>f, 'set xlabel "number of connections"'
	print >>f, 'set style fill solid'
	print >>f, 'set xrange [0:%d]' % (settings.max_peers + 1)
	print >>f, 'set yrange [0:*]'
	print >>f, 'set boxwidth 1'
	print >>f, 'plot "dots/frame%d.txt" using 1:2 with boxes' % tick
	f.close()

	if settings.plot_rank_histogram:
		os.system('gnuplot dots/render_rank_histogram%d.gnuplot &' % tick)

def plot_list(samples, name):
	f = open('dots/%s.txt' % name, 'w+')
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
	print >>f, 'plot "dots/%s.txt" using 1:2 with steps title "%s"' % (name, name)
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

	f = open('dots/%s.txt' % name, 'w+')
	counter = 0
	for i in samples:
		i.sort()
		if i == []: i.append(0)
		# print 10th 90th, 20th, 80th, 30th, 70th, 40th, 60th and 50th percentiles
		print >>f, '%d %d %d %d %d %d %d %d %d %d %d %d' \
			% (counter, min(i), max(i), \
			percentile(i, 0.10), percentile(i, 0.90), \
			percentile(i, 0.2), percentile(i, 0.8),\
			percentile(i, 0.3), percentile(i, 0.7), \
			percentile(i, 0.4), percentile(i, 0.6), \
			percentile(i, 0.5))
		if min(i) > 0 and min(i) == max(i): break
		counter += 1
	f.close();

	f = open('dots/render_%s.gnuplot' % name, 'w+')
	print >>f, 'set term png size 800,300'
	print >>f, 'set output "%s.png"' % name
	print >>f, 'set ylabel "%s"' % name
	print >>f, 'set xlabel "tick"'
	print >>f, 'set key right bottom'
	print >>f, 'plot "dots/%s.txt" using 1:2:3 with filledcurves closed title "min-max" lc rgb "#ffdddd",' % name,
	print >>f, '"dots/%s.txt" using 1:4:5 with filledcurves closed title "10th-90th percentile" lc rgb "#ffcccc",' % name,
	print >>f, '"dots/%s.txt" using 1:6:7 with filledcurves closed title "20th-80th percentile" lc rgb "#ffbbbb",' % name,
	print >>f, '"dots/%s.txt" using 1:8:9 with filledcurves closed title "30th-70th percentile" lc rgb "#ff9999",' % name,
	print >>f, '"dots/%s.txt" using 1:10:11 with filledcurves closed title "40th-60th percentile" lc rgb "#ff7777",' % name,
	print >>f, '"dots/%s.txt" using 1:12 with lines title "median" lc rgb "#cc5555"' % name,
	f.close()

	os.system('gnuplot dots/render_%s.gnuplot &' % name)


## main program ##

try: os.mkdir('plots')
except: pass
try: os.mkdir('dots')
except: pass
try: os.mkdir('frames')
except: pass

for i in xrange(0, int(settings.swarm_size * 3)):

	step()

	# add a new peer every other tick
	if len(peers_in_swarm) < settings.swarm_size and i % 2 == 0:
		add_new_peer(len(peers_in_swarm))

	render()

	tick += 1

plot_list(attempts_per_tick, 'connection_attempts')
plot_list(rejects_per_tick, 'connection_rejects')
plot_list(replacements_per_tick, 'connection_replacements')
plot_percentiles(startup, 'peer_startup')

