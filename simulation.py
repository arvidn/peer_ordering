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
swarm_size = 300

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

	maybe_connect_more_peers(n)

# take one step in the simulation
def step():
	global tick
	tick += 1
	print '==== TICK: %-4d ===' % tick

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
			try: known_peers[a].remove(n)
			except: pass
			try: known_peers[n].remove(a)
			except: pass
			connection_attempts[n].remove(a)

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

	os.system('sfdp -oframes/frame%d.png -Tpng dots/frame%d.dot' % (tick, tick))


try: os.mkdir('dots')
except: pass
try: os.mkdir('frames')
except: pass

for i in xrange(0, int(swarm_size * 1.5)):

	step()

	if (len(peers_in_swarm) < swarm_size):
		add_new_peer(len(peers_in_swarm))

	render()

