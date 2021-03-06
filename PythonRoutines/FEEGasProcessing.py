""""""

from psana import *
fee_gas_det_name='FEEGasDetEnergy'

class FEEGasProcessor(object):

    def __init__(self):
        self.fee_gas_det=Detector(fee_gas_det_name)

    def ShotEnergy(self, event): # in mJ
        fee_gas_evt=self.fee_gas_det.get(event)
        if fee_gas_evt is None:
            return None
        return (fee_gas_evt.f_11_ENRC()+fee_gas_evt.f_12_ENRC())/2.
        # currently averaging over 2 detectors

        #+fee_gas.f_13_ENRC()+fee_gas.f_14_ENRC())/float(4) 
        # there are 4 detectors in all, can average over however many
        # but as of 20171130 the other two do not appear to be working
