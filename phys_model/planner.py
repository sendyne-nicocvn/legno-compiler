import hwlib.device as devlib
import hwlib.block as blocklib
import hwlib.adp as adplib
import hwlib.hcdc.hcdcv2 as hcdclib
import phys_model.phys_util as phys_util
import phys_model.model_fit as model_fit


import random
import itertools


#import investigate_models

class ProfilePlanner:

  def __init__(self,block,loc,cfg):
    self.block = block
    self.loc = loc
    self.config = cfg

  def next_hidden(self):
    raise NotImplementedError

  def new_dynamic(self,cfg):
    raise NotImplementedError


  def next_dynamic(self):
    raise NotImplementedError



class BruteForcePlanner(ProfilePlanner):

  def __init__(self,block,loc,cfg,n,m):
    ProfilePlanner.__init__(self,block,loc,cfg)
    self.n = n					#outer dimensions of search space
    self.m = m					#resolution (linspace) of search space
    self.block = block
    self.loc = loc
    self.cfg = cfg

  def new_hidden(self):				#hidden code is a particular set of nmos,pmos, etc
    #print(self.config["nmos"].value)
    #help(self.config)
    #print(dir(self.config["nmos"]))
    #help(self.config["nmos"])
    hidden = {}
    for state in filter(lambda st: isinstance(st.impl, blocklib.BCCalibImpl), self.block.state):
      hidden[state] = phys_util.select_from_array(state.values,self.n)
    self._hidden_fields = list(hidden.keys())
    hidden_values = list(map(lambda k :hidden[k], self._hidden_fields))

    self.hidden_iterator = itertools.product(*hidden_values)
    self.dynamic_iterator = None

  def next_hidden(self):
    try:
      values = next(self.hidden_iterator)
      #print("values are ", values)
      return dict(zip(self._hidden_fields,values))
    except StopIteration:
      return None

  def new_dynamic(self):
    # build up dynamically changing codes
    assert(self.dynamic_iterator is None)
    variables = []
    blk = self.block
    for out in blk.outputs:
      variables += list(out.relation[self.config.mode].vars())

    dynamic = {}
    for inp in filter(lambda inp: inp.name in variables, blk.inputs):
      dynamic[inp] = phys_util.select_from_interval(inp.interval[self.config.mode],self.m)

    for data in filter(lambda dat: dat.name in variables, blk.data):
      dynamic[data] = phys_util.select_from_quantized_interval(data.interval[self.config.mode], data.quantize[self.config.mode], self.m)

    self._dynamic_fields = list(dynamic.keys())
    dynamic_values = list(map(lambda k :dynamic[k], self._dynamic_fields))
    self.dynamic_iterator = itertools.product(*dynamic_values)

  def next_dynamic(self):
    assert(not self.dynamic_iterator is None)
    try:
      values = next(self.dynamic_iterator)
      return dict(zip(self._dynamic_fields,values))
    except StopIteration:
      self.dynamic_iterator = None
      return None

class SinglePointPlanner(BruteForcePlanner):

  def __init__(self,block,loc,cfg,m):
    BruteForcePlanner.__init__(self,block,loc,cfg,0,m)

  def new_hidden(self):
    hidden = {}
    for state in filter(lambda st: isinstance(st.impl, blocklib.BCCalibImpl), self.block.state):
      hidden[state] = self.cfg[state.name].value

    self.hidden_iterator = hidden
    self.dynamic_iterator = None

  def next_hidden(self):
    value = self.hidden_iterator
    self.hidden_iterator = None
    return value



class SensitivityPlanner(BruteForcePlanner):
  def __init__(self,block,loc,cfg,n,m):
    BruteForcePlanner.__init__(self,block,loc,cfg,n,m)

  def new_hidden(self):

    svd = {}
    hidden = {}
    output_codes = []

    for state in filter(lambda st: isinstance(st.impl, blocklib.BCCalibImpl), self.block.state):
      hidden[state] = phys_util.select_from_array(state.values,self.n)
      svd[state] = self.config[state.name].value

    for state in hidden:
      for experiment_val in hidden[state]:
        new_row = dict(svd)
        new_row[state] = experiment_val
        #print("new_row is", new_row, "\n\n")
        output_codes.append(new_row)
        #print("output_codes is ", output_codes,"\n\n")
        #print("experiment_val is ", experiment_val)
        #print("output_codes[-1] is ", output_codes[-1])


    output_codes = [row for row in output_codes if row != dict(svd)]
    output_codes.append(dict(svd))


    self._hidden_fields = list(hidden.keys())
    hidden_values = list(map(lambda k :hidden[k], self._hidden_fields))

    #for state in filter(lambda st: isinstance(st.impl, blocklib.BCCalibImpl), self.block.state):
    #  hidden[state] = phys_util.select_from_array(state.values,self.n)
    #  svd[state] = self.config[state.name].value
    #  for experiment_val in hidden[state]:
    #    output_codes.append(svd)
    #    #print("output_codes is ", output_codes)
    #    print("experiment_val is ", experiment_val)
    #    print("output_codes[-1] is ", output_codes[-1])
    #    output_codes[-1][state] = experiment_val





    #print("_hidden_fields are: ", self._hidden_fields)
    #print("hidden_values are: ", hidden_values)
    #print("output_codes are: ", output_codes)

    #self.hidden_iterator = itertools.product(*hidden_values)
    #self.dynamic_iterator = None        

    self.hidden_iterator = GenericHiddenCodeIterator(output_codes)
    self.dynamic_iterator = None




class NeighborhoodPlanner(BruteForcePlanner):

  def __init__(self,block,loc,cfg,n,m):
    BruteForcePlanner.__init__(self,block,loc,cfg,n,m)

  def new_hidden(self):
    hidden = {}
    for state in filter(lambda st: isinstance(st.impl, blocklib.BCCalibImpl), self.block.state):
      #print("state is: ", state)
      valid = list(map(lambda delta: self.config[state.name].value + delta, range(-self.n,self.n+1)))
      hidden[state] = list(filter(lambda val: val in valid,state.values))
      #print("hidden[state] is :", hidden[state], "\n\n\n")
    self._hidden_fields = list(hidden.keys())
    hidden_values = list(map(lambda k :hidden[k], self._hidden_fields))
    self.hidden_iterator = itertools.product(*hidden_values)
    self.dynamic_iterator = None


class CorrelationPlanner(BruteForcePlanner):
  def __init__(self,block,loc,cfg,n,m):
    BruteForcePlanner.__init__(self,block,loc,cfg,n,m)

  def new_hidden(self):

    svd = {}
    hidden = {}
    correlation_pairs = []
    output_with_repeats = []
    output_without_repeats = []
    

    for state in filter(lambda st: isinstance(st.impl, blocklib.BCCalibImpl), self.block.state):
      hidden[state] = phys_util.select_from_array(state.values,self.n)
      svd[state] = self.config[state.name].value

    state_list = list(filter(lambda st: isinstance(st.impl, blocklib.BCCalibImpl), self.block.state))

    for element in itertools.combinations(state_list,2):
      correlation_pairs.append(element)

    for current_pair in correlation_pairs:
      for experiment_index in range(self.n):
        new_row = dict(svd)
        new_row[current_pair[0]] = hidden[current_pair[0]][experiment_index]
        new_row[current_pair[1]] = hidden[current_pair[1]][experiment_index]
        output_with_repeats.append(new_row)


    #remove duplicates
    for current_row in output_with_repeats:
      if current_row not in output_without_repeats:
        output_without_repeats.append(current_row)


    self._hidden_fields = list(hidden.keys())
    hidden_values = list(map(lambda k :hidden[k], self._hidden_fields))  

    self.hidden_iterator = GenericHiddenCodeIterator(output_without_repeats)
    self.dynamic_iterator = None

class FullCorrelationPlanner(BruteForcePlanner):
  def __init__(self,block,loc,cfg,n,m):
    BruteForcePlanner.__init__(self,block,loc,cfg,n,m)

  def new_hidden(self):

    svd = {} #start value dictionary
    hidden = {}
    correlation_pairs = []
    output_with_repeats = []
    output_without_repeats = []
    

    for state in filter(lambda st: isinstance(st.impl, blocklib.BCCalibImpl), self.block.state):
      hidden[state] = phys_util.select_from_array(state.values,self.n)
      svd[state] = self.config[state.name].value

    state_list = list(filter(lambda st: isinstance(st.impl, blocklib.BCCalibImpl), self.block.state))

    for element in itertools.combinations(state_list,2):
      correlation_pairs.append(element)

    for current_pair in correlation_pairs:
      for experiment_index_A in range(self.n):
        for experiment_index_B in range(self.n):
          new_row = dict(svd)
          new_row[current_pair[0]] = hidden[current_pair[0]][experiment_index_A]
          new_row[current_pair[1]] = hidden[current_pair[1]][experiment_index_B]
          output_with_repeats.append(new_row)


    #remove duplicates
    for current_row in output_with_repeats:
      if current_row not in output_without_repeats:
        output_without_repeats.append(current_row)

    #print(output_without_repeats)

    self._hidden_fields = list(hidden.keys())
    hidden_values = list(map(lambda k :hidden[k], self._hidden_fields))  

    self.hidden_iterator = GenericHiddenCodeIterator(output_without_repeats)
    self.dynamic_iterator = None


class GenericHiddenCodeIterator:
  def __init__(self,output_codes):
    self.index = 0
    self.output_codes = output_codes
    #print("in generic iterator output_codes is ", output_codes)

  def __iter__(self):
    return self

  def __next__(self):
    try:
      result = self.output_codes[self.index]
      #print("in generic iterator result is ", result)
      _output_fields = list(result.keys())
      print("_output_fields: ", _output_fields)
      output_values = list(map(lambda k :result[k], _output_fields))
      #print("!!!generic iterator called, returning: ", result)
    except IndexError:
      raise StopIteration
    self.index += 1
    return output_values

class RandomCodeIterator:
  def __init__(self,default_code,num_codes):
    random.seed()
    self.default_code = default_code
    self.code_index = 0
    self.codes_to_generate = num_codes


  def __iter__(self):
    return self

  def __next__(self):
    self.dev = hcdclib.get_device()
    self.blk = self.dev.get_block('mult')
    if self.code_index < self.codes_to_generate:
      current_output = {}
      for code in self.default_code:
        current_output[code] = random.randint(0,max(self.blk.state[code.name].values))
      _output_fields = list(current_output.keys())
      output_values = list(map(lambda k :current_output[k], _output_fields))

      self.code_index += 1
      return output_values
    else:
      raise StopIteration
    
class RandomPlanner(BruteForcePlanner):
  def __init__(self,block,loc,cfg,n,m):
    BruteForcePlanner.__init__(self,block,loc,cfg,n,m)

  def new_hidden(self):

    default_code = {}
    hidden = {}
    for state in filter(lambda st: isinstance(st.impl, blocklib.BCCalibImpl), self.block.state):
      default_code[state] = self.config[state.name].value
      hidden[state] = phys_util.select_from_array(state.values,self.n)

    self._hidden_fields = list(hidden.keys())


    num_codes = 50
    self.hidden_iterator = RandomCodeIterator(default_code, num_codes)
    self.dynamic_iterator = None


'''
class ModelBasedPlanner(BruteForcePlanner):
  def __init__(self,block,loc,cfg,n,m):
    BruteForcePlanner.__init__(self,block,loc,cfg,n,m)
  def new_hidden(self):

    default_code = {}
    for state in filter(lambda st: isinstance(st.impl, blocklib.BCCalibImpl), self.block.state):
      default_code[state] = self.config[state.name].value

    self.hidden_iterator = ExperimentalIterator(default_code)
    self.dynamic_iterator = None

class ExperimentalIterator(GenericHiddenCodeIterator):
  def __init__(self, default_code):
    random.seed()
    self.default_code = default_code
    self.experiments_run = 0
    self.preliminary_experiment_size = 15
    self.experiments_per_step = 10
    self.reached_convergence = False
    #print("in generic iterator output_codes is ", output_codes)

  def __iter__(self):
    return self

  def __next__(self):
    if self.experiments_run < self.preliminary_experiment_size:
      self.experiments_run += 1
      return generate_random_code(default_code)

    if self.experiments_run == self.preliminary_experiment_size:
      #FIT_MODELS_TO_DATA

    if ((self.experiments_run - self.preliminary_experiment_size) % self.experiments_per_step == 0) :
      #CHECK IF HAVE REACHED CONVERGENCE
      if ***good_enough***:
        return ***optimal code found***
      else:
        self.experiments_run += 1
        return generate_random_code(default_code)

    else:
      self.experiments_run += 1
      return generate_random_code(default_code)

  def generate_random_code(default_code):
    current_output = {}
    for state in default_code:
      current_output[state] = random.randint(0,current_output[state].values)
    return current_output

  def make_prediction():

  def fit_models_to_data():
    cost_model = fit_parameters("cost")
    param_A_model = fit_parameters("A")
    param_D_model = fit_parameters("D")

  def minimize_model();
'''
'''
ALGORITHM SPEC

(a*c + d)*x + e = z

1) Query some random points 
2) Fit the physical model parameters to the data
3) Using the physical model parameters, search for the hidden code h' that minimizes the extra error e(h)
4) Pick 10 NEW hidden codes at which to compare the predictions
5) Generate predictions for each hidden code
6) Run the experiment to get the real data at these 10 new codes
7) Compare the experimental data to the prediction
8) DOES THE PREDICTION REPRESENT THE EXPERIMENT WELL ENOUGH?
    YES)  Return h', and the physical model parameters
    NO)   return to 1 




'''
