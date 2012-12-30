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
import sys

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
parser.add_argument('--half-open-limit', dest='half_open_limit', default=2, type=int, help='the max number of outstanding connection attempts per peer')

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

# don't render the connection attempts in the state graph, as red dotted lines
parser.add_argument('--no-plot-attempts', dest='render_connection_attempts', default=True, action='store_const', const=False, \
	help='disable rendering of connection attempts (as red dotted lines). This may make the resulting graphs slightly easier to interpret')

# render node rank histogram for each step
parser.add_argument('--plot-rank-histogram', dest='plot_rank_histogram', default=False, action='store_const', const=True, help='render a histogram of node rank for each step')

# set this to 0 to supress debug logging, set to 2 to make it
# more verbose
parser.add_argument('--logging', dest='logging', default=0, type=int, help='enable logging (1=moderate logging 2=verbose logging)')

parser.add_argument('--no-plot-diameter', dest='plot_graph_diameter', default=True, action='store_const', const=False, help='disable calculating and plotting graph diameter')

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

# like known peers but have tried once and failed
retry_peers = {}

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

# the diameter of the graph, for each tick
diameter = []

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

	if len(known_peers[n]) == 0 and len(retry_peers[n]) > 0:
		known_peers[n] = retry_peers[n]
		retry_peers[n] = []

	if len(est_connections[n]) + len(connection_attempts[n]) >= settings.max_peers:
		return

	while len(est_connections[n]) + len(connection_attempts[n]) < settings.max_peers \
		and len(connection_attempts[n]) < settings.half_open_limit \
		and len(known_peers[n]) > 0:

		# if we're using peer priorities
		# pick the highest ranking peers
		# otherwise pick one at random
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
	retry_peers[n] = []

	if settings.logging > 1:
		print 'adding peer "%d", tracker: ', peers

	peers_in_swarm.add(n)
	join_time[n] = tick

	maybe_connect_more_peers(n)

# take one step in the simulation
def step():
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
				and not n in retry_peers[a] \
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
				retry_peers[n].append(a)

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

def graph_diameter(conns):

	# for each node, do a breadth first flood fill to
	# find the longest path away from it. Pick the longest
	# path encountered
	ret = 0
	for n in conns:
		cur_dist = 0
		queue = set()
		queue.add(n)
		distances = {}
		while True:

			# mark the nodes in queue with the current distance
			for cur_node in queue:
				if cur_node in distances: continue
				distances[cur_node] = cur_dist

			# replace queue with the adjacent node to those
			cur_dist += 1
			adjacent = set()
			for cur_node in queue:
				for adj in conns[cur_node]:
					# if we've already visited this node
					# don't add it
					if not adj in distances: adjacent.add(adj)

			queue = adjacent

			# if there are no more adjacent nodes left, we're done
			if len(queue) == 0: break

		ret = max(ret, cur_dist-1)

	return ret

def render():
	global tick
	f = open('out/dots/frame%d.dot' % tick, 'w+')

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

	if settings.render_connection_attempts:
		for n,conns in connection_attempts.iteritems():
			for c in conns:
				print >>f, '"%d" -- "%d" [dirType="forward", color=red, constraint=false, style=dotted, weight=0];' % (n, c)

	print >>f, '}'
	f.close()

	if settings.plot_graph:
		os.system('sfdp -oout/frames/frame%d.png -Tpng out/dots/frame%d.dot &' % (tick, tick))

	histogram = {}
	for n,conns in est_connections.iteritems():
		rank = len(conns)
		if not rank in histogram: histogram[rank] = 1
		else: histogram[rank] += 1

	f = open('out/dots/frame%d.txt' % tick, 'w+')
	for i,n in histogram.iteritems():
		print >>f, '%d %d' % (i, n)
	f.close();

	f = open('out/dots/render_rank_histogram%d.gnuplot' % tick, 'w+')
	print >>f, 'set term png size 600,300'
	print >>f, 'set output "out/plots/frame%d.png"' % tick
	print >>f, 'set ylabel "number of peers"'
	print >>f, 'set xlabel "number of connections"'
	print >>f, 'set style fill solid'
	print >>f, 'set xrange [0:%d]' % (settings.max_peers + 1)
	print >>f, 'set yrange [0:*]'
	print >>f, 'set boxwidth 1'
	print >>f, 'plot "out/dots/frame%d.txt" using 1:2 with boxes' % tick
	f.close()

	if settings.plot_rank_histogram:
		os.system('gnuplot out/dots/render_rank_histogram%d.gnuplot &' % tick)

	if settings.plot_graph_diameter:
		diameter.append(graph_diameter(est_connections))

def plot_list(samples, name, ylabel):
	f = open('out/dots/%s.txt' % name, 'w+')
	counter = 0
	for i in samples:
		print >>f, '%d %d' % (counter, i)
		counter += 1
	f.close();

	f = open('out/dots/render_%s.gnuplot' % name, 'w+')
	print >>f, 'set term png size 800,300'
	print >>f, 'set output "out/%s.png"' % name
	print >>f, 'set ylabel "%s"' % ylabel
	print >>f, 'set xlabel "tick"'
	print >>f, 'set yrange [0:*]'
	print >>f, 'plot "out/dots/%s.txt" using 1:2 with steps title "%s"' % (name, name)
	f.close()

	os.system('gnuplot out/dots/render_%s.gnuplot &' % name)

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

	f = open('out/dots/%s.txt' % name, 'w+')
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
		# when 90% of the peers have a full peer list, stop plotting
		if percentile(i, 0.1) == settings.max_peers: break
		counter += 1
	f.close();

	for xlimit in xrange(0, 60, 10):
		f = open('out/dots/render_%s_%d.gnuplot' % (name, xlimit), 'w+')
		print >>f, 'set term png size 800,300'
		print >>f, 'set output "out/%s_%d.png"' % (name, xlimit)
		print >>f, 'set ylabel "connected peers"'
		print >>f, 'set xlabel "tick"'
		print >>f, 'set key right bottom'
		print >>f, 'set xrange [0:%s]' % ('*' if xlimit == 0 else ('%d' % xlimit))
		print >>f, 'plot "out/dots/%s.txt" using 1:2:3 with filledcurves closed title "min-max" lc rgb "#ffdddd",' % name,
		print >>f, '"out/dots/%s.txt" using 1:4:5 with filledcurves closed title "10th-90th percentile" lc rgb "#ffcccc",' % name,
		print >>f, '"out/dots/%s.txt" using 1:6:7 with filledcurves closed title "20th-80th percentile" lc rgb "#ffbbbb",' % name,
		print >>f, '"out/dots/%s.txt" using 1:8:9 with filledcurves closed title "30th-70th percentile" lc rgb "#ff9999",' % name,
		print >>f, '"out/dots/%s.txt" using 1:10:11 with filledcurves closed title "40th-60th percentile" lc rgb "#ff7777",' % name,
		print >>f, '"out/dots/%s.txt" using 1:12 with lines title "median" lc rgb "#cc5555"' % name
		f.close()

		os.system('gnuplot out/dots/render_%s_%d.gnuplot &' % (name, xlimit))


## main program ##

try: os.mkdir('out')
except: pass
try: os.mkdir('out/plots')
except: pass
try: os.mkdir('out/dots')
except: pass
try: os.mkdir('out/frames')
except: pass

for i in xrange(0, int(settings.swarm_size * 3)):

	step()

	# add a new peer every other tick
	if len(peers_in_swarm) < settings.swarm_size and i % 2 == 0:
		add_new_peer(len(peers_in_swarm))

	render()

	tick += 1
	print '=== TICK: %-4d : %-4d ===\r' % (tick, settings.swarm_size * 3),
	sys.stdout.flush()

if settings.plot_graph_diameter:
	plot_list(diameter, 'graph_diameter', 'diameter')
plot_list(attempts_per_tick, 'connection_attempts', 'connection attempts')
plot_list(rejects_per_tick, 'connection_rejects', 'connection rejects')
plot_list(replacements_per_tick, 'connection_replacements', 'replaced connections')
plot_percentiles(startup, 'peer_startup')

