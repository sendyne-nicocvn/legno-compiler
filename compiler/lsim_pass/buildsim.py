import compiler.math_utils as mathutils

import runtime.models.exp_delta_model as deltalib
import runtime.models.exp_profile_dataset as proflib

import ops.base_op as baseoplib
import ops.generic_op as genoplib
import ops.op as oplib
import ops.parametric_surf as parsurflib

import hwlib.adp as adplib
import hwlib.block as blocklib
from scipy.integrate import ode

import hwlib.hcdc.llenums as llenums
import hwlib.hcdc.llcmd_compensate as llcmdcomp

import tqdm
import numpy as np
import math
import util.util as util

# physdb -- model physical model parameters
# model error -- model point errors across input space.
# interval -- model interval clipping
# quantize -- model quantization of digital values

SETTINGS = {
  'physdb': True,
  'model_error': True,
  'interval': True,
  'quantize': True
}

class ADPSim:

  def __init__(self):
    self._state_vars = []
    self._funcs = []
    self._emul = {}
    self.time_scale = 1.0

  def function(self,var):
    idx = self._funcs.index(var)
    return self._emul[var]


  def state_var(self,var):
    idx = self._state_vars.index(var)
    return self._emul[var]

  def variable(self,v):
    return self._emul[v]

  def set_function(self,name,emul):
    assert(not name in self._state_vars)
    assert(not name in self._funcs)
    self._funcs.append(name)
    self._emul[name] = emul


  def set_stvar(self,name,emul):
    assert(not name in self._state_vars)
    self._state_vars.append(name)
    self._emul[name] = emul

  @property
  def functions(self):
    return self._funcs


  @property
  def state_vars(self):
    return self._state_vars

  def __repr__(self):
    st = ""
    for stvar in self._state_vars:
      st += "=== State Var %s (%s) ===\n" % (stvar,self.sources[stvar.key])
      st += "deriv: %s\n" % self.derivs[stvar.key][1]
      st += "initc: %s\n" % self.init_conds[stvar.key][1]

    return st


class ADPSimResult:

  def __init__(self,sim):
    self.sim = sim
    self.state_vars = list(sim.state_vars)
    self.functions = list(sim.functions)

    self.values = {}
    for var in self.state_vars:
      self.values[var] = []

    for var in self.functions:
      self.values[var] = []

    self._time = []

  @property
  def num_vars(self):
    return len(self.state_vars)


  def times(self,rectify=True):
    times = self._time
    T = np.array(times)/self.sim.time_scale
    return T

  def data(self,variable,rectify=True):
    vals = self.values[variable]
    times = self.times(rectify)
    if rectify:
      scale_factor = self.sim.variable(variable).scale_factor
      print("var %s scf=%f" % (variable,scale_factor))
      V = np.array(list(vals))/scale_factor
    else:
      V = vals

    return times,V

  def add_point(self,t,xs,fs):
    assert(len(xs) == len(self.state_vars))
    assert(len(fs) == len(self.functions))

    self._time.append(t)
    for var,val in zip(self.state_vars,xs):
      self.values[var].append(val)

    for var,val in zip(self.functions,fs):
      self.values[var].append(val)



def identify_integrators(dev):
  integs = []
  for blk in dev.blocks:
    for mode in blk.modes:
      for out in blk.outputs:
        expr = out.relation[mode]
        is_integ = any(filter(lambda n: n.op == baseoplib.OpType.INTEG, \
                              expr.nodes()))
        if is_integ:
          integs.append((blk.name,mode,out.name))

  return integs

class ADPEmulVar:

  def __init__(self,var):
    self.var = var

  def compute(self,vardict):
    assert(str(self.var) in vardict)
    return vardict[str(self.var)]

class ADPEmulBlock:

  def __init__(self,board,adp,block,cfg,port,calib_obj):
    self.board = board
    self.block = block
    self.cfg = cfg
    self.loc = self.cfg.inst.loc
    self.port = port
    self.calib_obj = calib_obj
    self.inputs = {}
    self.user_defined = None
    self.npts = 10

    self.enable_phys = SETTINGS['physdb']
    self.enable_intervals = SETTINGS['interval']
    self.enable_quantize = SETTINGS['quantize']
    self.enable_model_error = SETTINGS['model_error']

    self._build_model(adp)


  @property
  def scale_factor(self):
    return self.port.scf

  def _get_digital_config(self):
    values = {}
    for stmt in self.cfg.stmts:
      if stmt.type == adplib.ConfigStmtType.CONSTANT:
        datum = self.block.data[stmt.name]
        dig_val = stmt.value

        # apply offset. Note that there may not be any data offsets
        # if the relation under the selected mode uses no digital fields.
        if self.enable_quantize:
          dig_val = datum.round_value(self.cfg.mode, dig_val)

        elif self.enable_intervals:
          raise NotImplementedError

        values[stmt.name] = dig_val

      if stmt.type == adplib.ConfigStmtType.EXPR:
        assert(hasattr(stmt,'outputs'))
        assert(hasattr(stmt,'inputs'))
        assert(hasattr(stmt,'input_port'))
        self.user_defined = (stmt.input_port, \
                             stmt.inputs, \
                             stmt.outputs)

    return values.items()

  def _get_error(self,vdict):
    if self.error_model is None:
      return 0.0

    if not  self.enable_phys  \
       or not self.enable_model_error:
      return 0.0

    values = {}
    for var,val in vdict.items():
      if var in self.error_model.variables:
        values[var] = val

    for var,val in self._get_digital_config():
        values[var] = val

    return self.error_model.get(values)


  def _concretize(self,expr):
    sub_dict = {}
    for var,val in self._get_digital_config():
        sub_dict[var] = genoplib.Const(val)



    conc_expr = expr.substitute(sub_dict)
    return conc_expr


  def _build_model(self,adp):
    out = self.block.outputs[self.port.name]
    model = deltalib.get_calibrated_output(self.board, \
                                           block=self.block, \
                                           loc=self.loc, \
                                           output=out, \
                                           cfg=self.cfg, \
                                           calib_obj=self.calib_obj)

    self.error_model = None

    # this
    llcmdcomp.compute_expression_fields(self.board,adp,self.cfg, \
                                        compensate=self.enable_phys)

    llcmdcomp.compute_constant_fields(self.board, \
                                      adp, \
                                      self.cfg, \
                                      compensate=self.enable_phys)

    if not model is None and self.enable_phys:
      dataset = proflib.load(self.board, \
                             self.block, \
                             self.loc, \
                             out, \
                             cfg=model.config, \
                             method=llenums.ProfileOpType.INPUT_OUTPUT)
      spec = self.block.outputs[self.port.name].deltas[self.cfg.mode]
      expr = spec.get_model(model.params)
 
      if not dataset is None:
        errors = model.errors(dataset,init_cond=False)
        surf = parsurflib.build_surface(block=self.block, \
                                        cfg=self.cfg, \
                                        port=out, \
                                        dataset=dataset, \
                                        output=errors, \
                                        npts=self.npts)
        self.error_model = surf


      else:
        print(model.config)
        for row in proflib.get_datasets_by_configured_block_instance(self.board, \
                                                                     self.block, \
                                                                     self.loc, \
                                                                     out, \
                                                                     model.config, \
                                                                     hidden=False):
          print(row)

        print("[warn] no dataset for %s %s" \
              % (self.block.name,self.loc))
        raise Exception("???")

    else:
      expr = self.block.outputs[self.port.name].relation[self.cfg.mode]

    self._expr = self._concretize(expr)


  def _compute(self,expr,values):
    vdict = dict(values)
    for inp,blks in self.inputs.items():
      val = 0.0
      for blk in blks:
        val += blk.compute(values)

      port = self.block.inputs[inp]

      if self.enable_intervals:
        val = port.interval[self.cfg.mode].clip(val)

      vdict[inp] = val


    if self.user_defined is None:
      vdict_sym = dict(map(lambda tup: (tup[0], \
                                        genoplib.Const(tup[1])),  \
                          vdict.items()))

      val = expr.substitute(vdict_sym).compute()
    else:
      input_port,inputs,outputs = self.user_defined
      inp_val = vdict[input_port]
      idx = util.nearest_value(inputs,inp_val,index=True)
      val = outputs[idx]


    val += self._get_error(vdict)

    port = self.block.outputs[self.port.name]
    val = port.interval[self.cfg.mode].clip(val)
    return val

  def compute(self,values):
    value = self._compute(self._expr,values)
    return value

  def connect(self,port,emul_blk):
    assert(isinstance(emul_blk,ADPEmulBlock)  \
           or isinstance(emul_blk,ADPEmulVar))
    assert(port in self.block.inputs)
    if not port.name in self.inputs:
      self.inputs[port.name] = []

    self.inputs[port.name].append(emul_blk)







class ADPStatefulEmulBlock(ADPEmulBlock):

  def __init__(self,board,adp,block,cfg,port,calib_obj):
    ADPEmulBlock.__init__(self,board,adp,block,cfg,port,calib_obj)
    self.variable = self.cfg.get(port.name).source

  def initial_cond(self):
    value =  self._init_cond
    value += self._get_error({})

    return value

  def derivative(self,values):
    value = self._compute(self._deriv,values)
    return value


  def _build_model(self,adp):
    #expr = blk.outputs[port.name].relation[cfg.mode]
    out = self.block.outputs[self.port.name]
    model = deltalib.get_calibrated_output(self.board, \
                                           block=self.block, \
                                           loc=self.loc, \
                                           output=out, \
                                           cfg=self.cfg, \
                                           calib_obj=self.calib_obj)

    llcmdcomp.compute_expression_fields(self.board, \
                                        adp, \
                                        self.cfg, \
                                        compensate=self.enable_phys)
    llcmdcomp.compute_constant_fields(self.board, \
                                      adp, \
                                      self.cfg, \
                                      compensate=self.enable_phys)
    self.error_model = None
    if not model is None and self.enable_phys:
      dataset = proflib.load(self.board, \
                           self.block, \
                           self.loc, \
                           out, \
                           model.config, \
                           method=llenums.ProfileOpType.INTEG_INITIAL_COND)

      spec = self.block.outputs[self.port.name].deltas[self.cfg.mode]
      expr = spec.get_model(model.params)

      if(not dataset is None):
        errors = model.errors(dataset,init_cond=True)
        surf = parsurflib.build_surface(block=self.block, \
                                        cfg=self.cfg, \
                                        port=out, \
                                        dataset=dataset, \
                                        output=errors, \
                                        npts=self.npts)
        self.error_model = surf
      else:
        print("[warn] no dataset for %s %s" \
              % (self.block.name,self.loc))


    else:
      expr = self.block.outputs[self.port.name].relation[self.cfg.mode]

    integ_expr = mathutils.canonicalize_integration_operation(expr)
    self._init_cond = self._concretize(integ_expr.init_cond).compute()
    self._deriv = self._concretize(integ_expr.deriv)



def is_integrator(block,cfg,port):
  if not block.outputs.has(port.name):
    return False

  expr = block.outputs[port.name].relation[cfg.mode]
  return any(filter(lambda n: n.op == baseoplib.OpType.INTEG, \
                    expr.nodes()))

def build_expr(dev,sim,adp,block,cfg,port):
  calib_obj = llenums.CalibrateObjective(adp \
                                         .metadata \
                                         .get(adplib.ADPMetadata.Keys.RUNTIME_CALIB_OBJ))
  if is_integrator(block,cfg,port):
    emul_block = ADPStatefulEmulBlock(dev,adp,block,cfg,port,calib_obj)
  else:
    emul_block = ADPEmulBlock(dev,adp,block,cfg,port,calib_obj)

  for input_port in block.inputs:
    for inst,port_name in map(lambda c: (c.source_inst,c.source_port), \
                            filter(lambda c: \
                                   c.dest_inst == cfg.inst and \
                                   c.dest_port == input_port.name, \
                                   adp.conns)):
          src_cfg = adp.configs.get(inst.block,inst.loc)
          src_blk = dev.get_block(inst.block)
          src_port = src_blk.outputs[port_name]

          if not is_integrator(src_blk,src_cfg,src_port):
            src_emul_block = build_expr(dev,sim,adp,src_blk,src_cfg,src_port)
            emul_block.connect(input_port,src_emul_block)
          else:
            var_name = src_cfg.get(port_name).source
            src_emul = ADPEmulVar(var_name)
            emul_block.connect(input_port,src_emul)

  return emul_block


def build_diffeqs(dev,adp):
  sim = ADPSim()
  for cfg in adp.configs:
    blk = dev.get_block(cfg.inst.block)
    for port in cfg.stmts_of_type(adplib.ConfigStmtType.PORT):
      if is_integrator(blk,cfg,port):
        emul_block = build_expr(dev,sim,adp,blk,cfg,port)
        sim.set_stvar(emul_block.variable, emul_block)

  for cfg in adp.configs:
    blk = dev.get_block(cfg.inst.block)
    for port in cfg.stmts_of_type(adplib.ConfigStmtType.PORT):
      source_var = cfg.get(port.name).source
      if not source_var is None and \
         isinstance(source_var,genoplib.Var) and\
         not source_var in sim.state_vars:
        emul_block = build_expr(dev,sim,adp,blk,cfg,port)
        sim.set_function(source_var, emul_block)


  return sim

def build_simulation(dev,adp):
  sim = build_diffeqs(dev,adp)
  sim.time_scale = 1.0/adp.tau
  return sim


def next_state(sim,values):
  vdict = dict(zip(map(lambda v: "%s" % v, \
                       sim.state_vars),values))
  result = [0.0]*len(sim.state_vars)
  for idx,v in enumerate(sim.state_vars):
    result[idx] = sim.state_var(v).derivative(vdict)

  return result

def func_state(sim,values):
  vdict = dict(zip(map(lambda v: "%s" % v, \
                       sim.state_vars),values))
  result = [0.0]*len(sim.functions)
  for idx,v in enumerate(sim.functions):
    result[idx] = sim.function(v).compute(vdict)

  return result


def run_simulation(sim,sim_time):

  def dt_func(t,vs):
    return next_state(sim,vs)


  time = sim_time*sim.time_scale
  n = 300.0
  dt = time/n

  res = ADPSimResult(sim)


  state_vars = list(sim.state_vars)
  if len(state_vars) == 0:
    for t in np.linspace(0,time,int(n)):
      res.add_point(t,[])

    return res

  r = ode(dt_func).set_integrator('zvode', \
                                  method='bdf')

  x0 = list(map(lambda v: sim.state_var(v).initial_cond(), \
                state_vars))
  r.set_initial_value(x0,t=0.0)
  tqdm_segs = 500
  last_seg = 0
  with tqdm.tqdm(total=tqdm_segs) as prog:
    while r.successful() and r.t < time:
        res.add_point(r.t,r.y,func_state(sim,r.y))
        r.integrate(r.t + dt)
        # update tqdm
        seg = int(tqdm_segs*float(r.t)/float(time))
        if seg != last_seg:
            prog.n = seg
            prog.refresh()
            last_seg = seg


  return res

def get_dsexpr_trajectories(dev,adp,sim,res):
  dataset = {}
  times = res.times(rectify=True)
  for stvar in res.state_vars:
    _,V = res.data(stvar,rectify=True)
    dataset[stvar.name] = V

  for func in res.functions:
    _,V = res.data(func,rectify=True)
    dataset[func.name] = V

  return times,dataset
