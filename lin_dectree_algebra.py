import json
import phys_model.lin_dectree as lin_dectree
import ops.generic_op as genoplib
import ops.lambda_op as lambdalib
import copy
import ops.opparse as parselib

def reconstruct(leaf_node_list,boundaries_to_ignore,default_boundaries):

	if len(leaf_node_list) <= 1:
		return leaf_node_list[0]
	#otherwise continue

	boundary_freq = {'pmos':{},\
	                'nmos':{},\
	                'gain_cal':{},\
	                'bias_out':{},\
	                'bias_in0':{},\
	                'bias_in1':{}}

	#this bit is nastily hardcoded atm
	#initialise the boundary_freq_list to fill the entire range with zeroes
	for var in boundary_freq:
		for i in range(default_boundaries[var][0], 2*default_boundaries[var][1]):
			boundary_freq[var][i*0.5] = 0

	#include upper bound
	for var in boundary_freq:
		boundary_freq[var][float(boundaries_to_ignore[var][1])] = 0
	#boundary_freq initialised now

	#this actually performs the count, constructing boundary_freq
	for leaf in leaf_node_list:
		for var in leaf.region.bounds:
			boundary_freq[var][float(leaf.region.bounds[var][0])]+=1
			boundary_freq[var][float(leaf.region.bounds[var][1])]+=1

	#as janky as it is, boundaries ending in .5 are upper bounds, and so their tally should be added on to the fully rounded integer that is above them
	#the following adds all .5 tallies to the integer above
	for var in boundary_freq:
		for boundary in boundary_freq[var]:
			if not boundary % 1 == 0:
				boundary_freq[var][boundary+0.5] += boundary_freq[var][boundary]
				boundary_freq[var][boundary] = 0

	#boundaries which exist in the boundaries_to_ignore dict are trivial and will have a large amount of hits, so they need to be set to 0
	for var in boundary_freq:
		for boundary in boundaries_to_ignore[var]:
			boundary_freq[var][boundary] = 0

	max_freq = 0
	max_loc = 0.0
	max_var = ""
	for var in boundary_freq:
		max_boundary_loc = max(boundary_freq[var].keys(), key=(lambda key: boundary_freq[var][key]))
		max_boundary_val = boundary_freq[var][max_boundary_loc]
		if max_boundary_val > max_freq:
			max_freq = max_boundary_val
			max_loc = max_boundary_loc
			max_var = var


	#time to make the first decision node


	#left leaves are below the val, right leaves are above
	#find all the leaves which have a upper bound less than or equal to 
	#val-0.5, they go in the left
	#and then find all leaves which have a lower bound greater than or equal to
	#val, and they go in the right
	left_leaves = []
	right_leaves = []

	for leaf in leaf_node_list:

		#print("leaf.region.bounds: ",leaf.region.bounds)
		#check if leaf lower bound is greater or equal to boundary 
		if leaf.region.bounds[max_var][0] >= max_loc:
			right_leaves.append(leaf)

		#check if leaf upper bound is less than or equal to boundary - 0.5
		elif leaf.region.bounds[max_var][1] <= max_loc:
			left_leaves.append(leaf)

	boundaries_to_ignore[max_var].append(max_loc)

	left_boundaries_to_ignore = copy.deepcopy(boundaries_to_ignore)
	right_boundaries_to_ignore = copy.deepcopy(boundaries_to_ignore)
	left_branch = reconstruct(left_leaves,left_boundaries_to_ignore,default_boundaries)
	right_branch = reconstruct(right_leaves,right_boundaries_to_ignore,default_boundaries)

	

	node = lin_dectree.DecisionNode(max_var,max_loc,left_branch,right_branch)

	return node

def is_valid_region(region):
	is_valid = True
	for var in region.bounds:
			lower = region.bounds[var][0]
			upper = region.bounds[var][1]
			if upper < lower:
				is_valid = False
				break
	return is_valid


def op_apply1(func, leaves):
   for leaf in leaves:
      new_leaf = leaf.copy()
      new_leaf.expr = func(leaf.expr)
      yield new_leaf

def op_apply2(func, leaves1, leaves2):
	for leaf1 in leaves1:
		for leaf2 in leaves2:
			reg = leaf1.region.overlap(leaf2.region)
			expr = func(leaf1.expr,leaf2.expr)
			if is_valid_region(reg):
				yield lin_dectree.RegressionLeafNode(expr, region = reg)



#pass in a genoplib expr


def eval_expr(e,subs):
	if e.op == genoplib.OpType.VAR:
		return subs[e.name]
	elif e.op == genoplib.OpType.PAREN:
		return eval_expr(e.expr,subs)
	elif e.op == genoplib.OpType.ADD:
		leaves1 = eval_expr(e.args[0],subs)
		leaves2 = eval_expr(e.args[1],subs)
		return list(op_apply2(lambda a, b: genoplib.Add(a,b), leaves1, leaves2))
	elif e.op == genoplib.OpType.MULT:
		leaves1 = eval_expr(e.args[0],subs)
		leaves2 = eval_expr(e.args[1],subs)
		return list(op_apply2(lambda a, b: genoplib.Mult(a,b), leaves1, leaves2))
	elif e.op == genoplib.OpType.POW:
		leaves = eval_expr(e.args[0],subs)
		power = eval_expr(e.args[1],subs)
		return list(op_apply2(lambda base,exponent: lambdalib.Pow(base,exponent), leaves, power))
	else:
		raise NotImplementedError


default_boundaries = {'pmos':[0,7],\
		            'nmos':[0,7],\
		            'gain_cal':[0,63],\
		            'bias_out':[0,63],\
		            'bias_in0':[0,63],\
		            'bias_in1':[0,63]}\

boundaries_to_ignore = dict(default_boundaries)

with open("static_dectree_param_A.json") as fh:
  serialized_dectree_dict_A = json.load(fh)
dectree_A = lin_dectree.DecisionNode.from_json(serialized_dectree_dict_A)

with open("static_dectree_cost.json") as fh:
  serialized_dectree_dict_B = json.load(fh)
dectree_B = lin_dectree.DecisionNode.from_json(serialized_dectree_dict_B)

A = dectree_A.concretize().leaves()
B = dectree_B.concretize().leaves()

expr = parselib.parse_expr("A^B")
variable_bindings = {"A": A, "B": B}
leaf_list = eval_expr(expr, variable_bindings) 

tree = reconstruct(leaf_list,boundaries_to_ignore,default_boundaries)

print(tree.find_minimum())
print(tree.pretty_print())

'''

#############ALGORITHM EXPLANATION###################

-define variable = dimension = one of pmos, nmos, bias_in0.....

every decision node implements a single "boundary" on a single variable, splitting it into an "above" and "below" region

for every point in the domain, a single tree specifies a single expr which is valid at that point,
the total domain being subdivided into many different valid regions (one for each leaf node)

when you combine two trees, you use a similar method to finding the cartesian product of the leaves of each tree,
where the region of each leaf is "overlapped"/"intersected"/"AND'ed" with that of the other. in the space
that satisfies both of the valid domains (the overlapping region), you can perform any of the genoplib
expression operations on the two source leaves you are working with.

to find the AND operation of the two regions, you are looking for the space where both leaves are valid. Each variable
of a leaf node will be assigned an upper and lower bound by the region property of the object. To calculate the region
in which both are valid, for each variable you must take the larger of the two lower bounds and the smaller of the two
upper bounds.

In some cases, two leaves from separate trees will not have any amount of overlap in their valid regions, this case
will present itself where the lower bound of the valid region is larger than the upper bound - this is easy to check
for, and leaves in the produced tree can simply be deleted from the combined tree. The regions of the remaining 
leaves should fully cover the entire possible input space. (maybe this is worth checking) >>>write a valid checker for this

this process will leave you with a flat list of leaves, with their relevant regions.

the next step is to reconstruct the decision tree that leaves you with these regions (i am not sure whether you want to 
include the regions you have deleted in this, as they may include important information that is required)

the input space is fully subdivided and fully covered by the valid regions (i think)

therefore the next step is to figure out how many of each leaf satisfy each possible decision node (each upper and lower
bound on any variable is a decision node)

this should give an idea of the hierarchy of decision nodes, as the boundary which the largest number of leaves satisfy will
be highest in the tree

the highest number will be at the top of the tree, after that, the data will need to be regathered as the leaves which
do and dont satisfy that condition need to be treated as entirely separate as branches cannot recombine

you need to remove the satisfied boundary from those that you consider in the child branches

so to do this you take the leaves which do satisfy the top decision node, and find the most satisfied boundary in that dataset
 -> do the same for the leaves which dont satisfy the top decision node 

the process can be completed recursively, splitting each dataset on each decision node to build up the structure of the tree
'''
