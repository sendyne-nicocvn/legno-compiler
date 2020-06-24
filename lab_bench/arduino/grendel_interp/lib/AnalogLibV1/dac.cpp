#include "AnalogLib.h"
#include <float.h>
#include "assert.h"
#include "calib_util.h"
#include "slice.h"
#include "dac.h"

void Fabric::Chip::Tile::Slice::Dac::computeInterval(dac_state_t& state,
                                                     port_type_t port, float& min, float& max){
  float ampl = 2.0;
  switch(port){
  case out0Id:
    ampl = state.range == RANGE_HIGH ? 20.0 : 2.0;
    break;
  default:
    error("dac was supplied unknown port");
  }
  min = -ampl;
  max = ampl;
}

float Fabric::Chip::Tile::Slice::Dac::computeInput(dac_state_t& codes, float output){
  float sign = util::sign_to_coeff(codes.inv);
  float rng = util::range_to_coeff(codes.range);
  return output/(sign*rng);
}

float Fabric::Chip::Tile::Slice::Dac::computeOutput(dac_state_t& codes){
  float sign = util::sign_to_coeff(codes.inv);
  float rng = util::range_to_coeff(codes.range);
  float const_val = (codes.const_code - 128.0)/128.0;
  return sign*rng*const_val;
}
void Fabric::Chip::Tile::Slice::Dac::update(dac_state_t codes){
  this->m_state = codes;
  updateFu();
  if(codes.source == DSRC_MEM){
    setConstantCode(codes.const_code);
  }
  setSource(codes.source);
  // restore exact state. The gain_val field clobbered a bit by setConstantCode
  this->m_state = codes;
}

void Fabric::Chip::Tile::Slice::Dac::setEnable (
	bool enable
)
{
	this->m_state.enable = enable;
	setParam0 ();
	setParam1 ();
}

void Fabric::Chip::Tile::Slice::Dac::setInv (
                                             bool inverse // whether output is negated
) {
  this->m_state.inv = inverse;
	setParam0();
}

void Fabric::Chip::Tile::Slice::Dac::setRange (
	// default is 2uA mode
	range_t range // 20 uA mode
) {
  assert(range != RANGE_LOW);
  this->m_state.range = range;
	setEnable (this->m_state.enable);
}

void Fabric::Chip::Tile::Slice::Dac::setSource (dac_source_t src) {
	/*record*/
  this->m_state.source = src;
  bool memory = (src == DSRC_MEM);
  bool external = (src == DSRC_EXTERN);
	switch (parentSlice->sliceId) {
		case slice0: parentSlice->parentTile->slice0DacOverride = memory; break;
		case slice1: parentSlice->parentTile->slice1DacOverride = memory; break;
		case slice2: parentSlice->parentTile->slice2DacOverride = memory; break;
		case slice3: parentSlice->parentTile->slice3DacOverride = memory; break;
	}
	if (external) {
		parentSlice->parentTile->setParallelIn ( external );
	}

	unsigned char cfgTile = 0b00000000;
	cfgTile += parentSlice->parentTile->slice0DacOverride ? 1<<7 : 0;
	cfgTile += parentSlice->parentTile->slice1DacOverride ? 1<<6 : 0;
	cfgTile += parentSlice->parentTile->slice2DacOverride ? 1<<5 : 0;
	cfgTile += parentSlice->parentTile->slice3DacOverride ? 1<<4 : 0;
	parentSlice->parentTile->controllerHelperTile ( 11, cfgTile );

	setEnable (
		this->m_state.enable
	);
}

void Fabric::Chip::Tile::Slice::Dac::setConstantCode (
	unsigned char constantCode // fixed point representation of desired constant
	// 0 to 255 are valid
) {
  this->m_state.const_code = constantCode;
  setSource(DSRC_MEM);
	parentSlice->parentTile->parentChip->parentFabric->cfgCommit();
	unsigned char selLine = 0;
	switch (parentSlice->sliceId) {
		case slice0: selLine = 7; break;
		case slice1: selLine = 8; break;
		case slice2: selLine = 9; break;
		case slice3: selLine = 10; break;
	}
	unsigned char cfgTile = endian (constantCode);
	parentSlice->parentTile->controllerHelperTile ( selLine, cfgTile );
}

void Fabric::Chip::Tile::Slice::Dac::setConstant(float constant){
  if(-1.001 < constant && constant< 1.001){
    setConstantCode(min(round(constant*128.0+128.0),255));
  }
  else{
    sprintf(FMTBUF,"dac.setConstant: only accepts constants between -1 and 1, set %f", constant);
    error(FMTBUF);
  }
}

void Fabric::Chip::Tile::Slice::Dac::defaults(){
  this->m_state.inv = false;
  this->m_state.range = RANGE_MED;
  this->m_state.pmos = 0;
  this->m_state.nmos = 0;
  this->m_state.gain_cal = 0;
  this->m_state.const_code = 128;
  this->m_state.enable = false;
  this->m_is_calibrated = false;
	setAnaIrefNmos ();
}
Fabric::Chip::Tile::Slice::Dac::Dac (
	Chip::Tile::Slice * parentSlice
) :
	FunctionUnit(parentSlice, unitDac)
{

	out0 = new Interface(this, out0Id);
	tally_dyn_mem <Interface> ("DacOut");
  defaults();
}

/*Set enable, invert, range, clock select*/
void Fabric::Chip::Tile::Slice::Dac::setParam0 () const {
	unsigned char cfgTile = 0;
  bool external = (this->m_state.source == DSRC_EXTERN
                   or this->m_state.source == DSRC_MEM);
  bool lut0 = (this->m_state.source == DSRC_LUT0);
  bool is_hiRange = (this->m_state.range == RANGE_HIGH);
  //bool is_inverse = (this->m_state.inv);
  bool is_inverse = (this->m_state.inv);
	cfgTile += this->m_state.enable ? 1<<7 : 0;
	cfgTile += (is_inverse) ? 1<<6 : 0;
	cfgTile += (is_hiRange ? dacHi : dacMid) ? 1<<5 : 0;
	cfgTile += (external) ? extDac : ( lut0 ? lutL : lutR )<<0;
	setParamHelper (0, cfgTile);
}

/*Set calDac, input select*/
void Fabric::Chip::Tile::Slice::Dac::setParam1 () const {
	unsigned char calDac =  this->m_state.gain_cal;
	if (calDac<0||63<calDac) error ("calDac out of bounds");
	unsigned char cfgTile = 0;
  bool external = (this->m_state.source == DSRC_EXTERN
                   or this->m_state.source == DSRC_MEM);
  bool lut0 = (this->m_state.source == DSRC_LUT0);
	cfgTile += calDac<<2;
  cfgTile += (external) ? extDac : ( lut0 ? lutL : lutR )<<0;
	setParamHelper (1, cfgTile);
}

/*Helper function*/
void Fabric::Chip::Tile::Slice::Dac::setParamHelper (
	unsigned char selLine,
	unsigned char cfgTile
) const {
	if (selLine<0||1<selLine) error ("selLine out of bounds");

	/*DETERMINE SEL_COL*/
	unsigned char selCol;
	switch (parentSlice->sliceId) {
		case slice0: selCol = 6; break;
		case slice1: selCol = 3; break;
		case slice2: selCol = 7; break;
		case slice3: selCol = 4; break;
		default: error ("DAC invalid slice"); break;
	}

	Chip::Vector vec = Vector (
		*this,
		6,
		selCol,
		selLine,
		endian (cfgTile)
	);

	parentSlice->parentTile->parentChip->cacheVec (
		vec
	);
}




void Fabric::Chip::Tile::Slice::Dac::setAnaIrefNmos () const {
	unsigned char selRow;
	unsigned char selCol=2;
	unsigned char selLine;
  util::test_iref(this->m_state.nmos);
	switch (parentSlice->sliceId) {
  case slice0: selRow=0; selLine=3; break;
  case slice1: selRow=1; selLine=0; break;
  case slice2: selRow=0; selLine=2; break;
  case slice3: selRow=1; selLine=1; break;
  default: error ("DAC invalid slice"); break;
	}
	unsigned char cfgTile = endian(parentSlice->parentTile->parentChip->cfgBuf[parentSlice->parentTile->tileRowId][parentSlice->parentTile->tileColId][selRow][selCol][selLine]);
	cfgTile = (cfgTile & 0b00111000) + (this->m_state.nmos & 0b00000111);

	Chip::Vector vec = Vector (
                             *this,
                             selRow,
                             selCol,
                             selLine,
                             endian (cfgTile)
                             );

	parentSlice->parentTile->parentChip->cacheVec (
                                                 vec
                                                 );

}
