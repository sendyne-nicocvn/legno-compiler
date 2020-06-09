import hwlib2.hcdc.llenums as enums
from hwlib2.block import *
import ops.opparse as parser
import ops.interval as interval

integ = Block('integ',BlockType.COMPUTE, \
            [enums.RangeType, \
             enums.RangeType, \
             enums.SignType])


integ.modes.add_all([
  ['m','m','+'],
  ['m','m','-'],
  ['m','h','+'],
  ['m','h','-'],
  ['h','m','+'],
  ['h','m','-'],
  ['h','h','+'],
  ['h','h','-']

])

integ.inputs.add(BlockInput('x',BlockSignalType.ANALOG, \
                           ll_identifier=enums.PortType.IN0))
integ.inputs['x'] \
    .interval.bind(['m','_','_'],interval.Interval(-2,2))
integ.inputs['x'] \
    .interval.bind(['h','_','_'],interval.Interval(-20,20))

integ.outputs.add(BlockOutput('z',BlockSignalType.ANALOG, \
                             ll_identifier=enums.PortType.OUT0))
integ.outputs['z'] \
    .interval.bind(['_','m','_'],interval.Interval(-2,2))
integ.outputs['z'] \
    .interval.bind(['_','h','_'],interval.Interval(-20,20))


integ.data.add(BlockData('z0',BlockDataType.CONST))
integ.data['z0'] \
    .interval.bind(['_','_','_'],interval.Interval(-1,1))
integ.data['z0'] \
    .quantize.bind(['_','_','_'],Quantize(256,QuantizeType.LINEAR))


integ.outputs['z'].relation \
                 .bind(['m','m','+'],parser.parse_expr('integ(x,(2.0*z0))'))

integ.outputs['z'].relation \
                 .bind(['m','h','+'],parser.parse_expr('integ((10.0*x),(20.0*z0))'))

integ.outputs['z'].relation \
                 .bind(['h','m','+'],parser.parse_expr('integ((0.1*x),(0.2*z0))'))

integ.state.add(BlockState('ic_code',
                          values=range(0,256), \
                          state_type=BlockStateType.DATA))
integ.state['ic_code'].impl.set_variable('z0')
integ.state['ic_code'].impl.set_default(128)



for field in ['enable','exception']:
  integ.state.add(BlockState(field,
                          values=enums.BoolType, \
                          state_type=BlockStateType.CONSTANT))
  integ.state[field].impl.bind(enums.BoolType.TRUE)

bcarr = BlockStateArray('cal_enable', \
                        indices=list(range(0,3)), \
                        values=enums.BoolType, \
                        length=3,\
                        default=enums.BoolType.FALSE)


for en_number in range(0,3):
  field = "cal_enable%d" % en_number
  integ.state.add(BlockState(field,
                             values=enums.BoolType, \
                             array=bcarr,
                             index=en_number,
                             state_type=BlockStateType.CONSTANT))
  integ.state[field].impl.bind(enums.BoolType.FALSE)


integ.state.add(BlockState('inv',  \
                           state_type= BlockStateType.MODE, \
                           values=enums.SignType))

integ.state['inv'] \
   .impl.bind(['_','_','+'], enums.SignType.POS)

integ.state['inv'] \
   .impl.bind(['_','_','-'], enums.SignType.NEG)



bcarr = BlockStateArray('range', \
                        indices=enums.PortType, \
                        values=enums.RangeType, \
                        length=3,\
                        default=enums.RangeType.MED)

integ.state.add(BlockState('range_in',  \
                        state_type= BlockStateType.MODE, \
                         values=enums.RangeType, \
                         array=bcarr, \
                         index=enums.PortType.IN0))

integ.state['range_in'] \
   .impl.bind(['m','_','_'], enums.RangeType.MED)
integ.state['range_in'] \
   .impl.bind(['h','_','_'], enums.RangeType.HIGH)


integ.state.add(BlockState('range_out',  \
                          state_type= BlockStateType.MODE, \
                          values=enums.RangeType, \
                          array=bcarr, \
                          index=enums.PortType.OUT0))

integ.state['range_out'] \
   .impl.bind(['_','m','_'], enums.RangeType.MED)
integ.state['range_out'] \
   .impl.bind(['_','h','_'], enums.RangeType.HIGH)


bcarr = BlockStateArray('port_cal', \
                        indices=enums.PortType, \
                        values=range(0,32), \
                        length=3,\
                        default=16)


integ.state.add(BlockState('port_cal_in',  \
                           state_type= BlockStateType.CALIBRATE, \
                           values=range(0,32), \
                           array=bcarr, \
                           index=enums.PortType.IN0))
integ.state['port_cal_in'].impl.set_default(16)


integ.state.add(BlockState('port_cal_out',  \
                           state_type= BlockStateType.CALIBRATE, \
                           values=range(0,32), \
                           array=bcarr, \
                           index=enums.PortType.OUT0))
integ.state['port_cal_out'].impl.set_default(16)

integ.state.add(BlockState('ic_cal',
                        values=range(0,32), \
                        state_type=BlockStateType.CALIBRATE))
integ.state['ic_cal'].impl.set_default(16)

integ.state.add(BlockState('pmos',
                        values=range(0,8), \
                        state_type=BlockStateType.CALIBRATE))
integ.state['pmos'].impl.set_default(3)
integ.state.add(BlockState('nmos',
                        values=range(0,8), \
                        state_type=BlockStateType.CALIBRATE))
integ.state['nmos'].impl.set_default(3)


