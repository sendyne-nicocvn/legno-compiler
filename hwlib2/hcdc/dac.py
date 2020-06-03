import hwlib2.hcdc.llenums as enums
from hwlib2.block import *
import ops.opparse as parser

class HLDACSourceType(Enum):
  DYNAMIC = 'dyn'
  CONST = 'const'

dac = Block('dac',BlockType.COMPUTE, \
            [HLDACSourceType,enums.RangeType])
dac.modes.add_all([
  ['const','m'],
  ['const','h'],
  ['dyn','m'],
  ['dyn','h']

])
dac.inputs.add(BlockInput('x', BlockSignalType.DIGITAL, \
                          ll_identifier=enums.PortType.IN0))
dac.outputs.add(BlockOutput('z', BlockSignalType.ANALOG, \
                            ll_identifier=enums.PortType.OUT0))

dac.outputs['z'].relation.bind(['dyn','m'], \
                               parser.parse_expr('2.0*x'))
dac.outputs['z'].relation.bind(['dyn','h'], \
                               parser.parse_expr('20.0*x'))
dac.outputs['z'].relation.bind(['const','m'], \
                               parser.parse_expr('2.0*c'))
dac.outputs['z'].relation.bind(['const','h'], \
                               parser.parse_expr('20.0*c'))

dac.outputs['z'] \
    .interval.bind(['_','h'],interval.Interval(-20,20))
dac.outputs['z'] \
    .interval.bind(['_','m'],interval.Interval(-2,2))



dac.data.add(BlockData('c', BlockDataType.CONST))
dac.data['c'] \
    .interval.bind(['_','_'],interval.Interval(-1,1))
dac.data['c'] \
    .quantize.bind(['_','_'],Quantize(256,QuantizeType.LINEAR))

# bind codes, range
dac.state.add(BlockState('inv',
                        values=enums.SignType, \
                        state_type=BlockStateType.CONSTANT))
dac.state['inv'].impl.bind(enums.SignType.POS)

dac.state.add(BlockState('enable',
                        values=enums.BoolType, \
                        state_type=BlockStateType.CONSTANT))
dac.state['enable'].impl.bind(enums.BoolType.TRUE)

dac.state.add(BlockState('range',  \
                        state_type= BlockStateType.MODE, \
                        values=enums.RangeType,
))

dac.state['range'] \
   .impl.bind(['_','m'], enums.RangeType.MED)
dac.state['range'] \
   .impl.bind(['_','h'], enums.RangeType.HIGH)


dac.state.add(BlockState('source', BlockStateType.CONNECTION, \
                        values=enums.DACSourceType))
dac.state['source'].impl.source('lut',['@','@',0,0],'x', \
                                enums.DACSourceType.LUT0)
dac.state['source'].impl.source('lut',['@','@',2,0],'x', \
                                enums.DACSourceType.LUT1)
dac.state['source'].impl.set_default(enums.DACSourceType.MEM)


dac.state.add(BlockState('dynamic', BlockStateType.MODE, \
                         values=enums.BoolType))
dac.state['dynamic'] \
   .impl.bind(['const','_'], enums.BoolType.TRUE)
dac.state['dynamic'] \
   .impl.bind(['dyn','_'], enums.BoolType.FALSE)


dac.state.add(BlockState('gain_cal',
                        values=range(0,32), \
                        state_type=BlockStateType.CALIBRATE))
dac.state['gain_cal'].impl.set_default(16)


dac.state.add(BlockState('pmos',
                        values=range(0,8), \
                        state_type=BlockStateType.CALIBRATE))
dac.state['pmos'].impl.set_default(3)

dac.state.add(BlockState('nmos',
                        values=range(0,8), \
                        state_type=BlockStateType.CALIBRATE))
dac.state['nmos'].impl.set_default(3)



dac.state.add(BlockState('const_code',
                          values=range(0,256), \
                          state_type=BlockStateType.DATA))
dac.state['const_code'].impl.set_variable('c')
dac.state['const_code'].impl.set_default(128)

