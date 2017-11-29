"""This code for online monitoring of the Scienta Hemispherical 
Electron Spectrometer"""
# Standard Python imports
from psana import *
import numpy as np
import cv2
import time

# This class for processing SHES data
from SHESPreProcessing import SHESPreProcessor

# This for estimating photon energy from ebeam L3 energy
from L3EnergyProcessing import L3EnergyProcessor
from FEEGasProcessing import FEEGasProcessor

# Import double-ended queue
from collections import deque

# 2D histogram from old psana code
from skbeam.core.accumulators.histogram import Histogram

# Imports for plotting
from psmon.plots import XYPlot,Image,Hist,MultiPlot
from psmon import publish
publish.local=True # changeme

# Imports for parallelisation
from mpi4py import MPI
comm = MPI.COMM_WORLD
rank = comm.Get_rank() # which core am I being run on
size = comm.Get_size() # no. of CPUs being used    

# Set parameters
#ds=DataSource("exp=AMO/amon0816:run=228:smd:dir=/reg/d/psdm/amo/amon0816/xtc:live")
ds=DataSource("exp=AMO/amox23616:run=86:smd:dir=/reg/d/psdm/amo/amox23616/xtc:live")
# TODO change to access the shared memory

threshold=500 # for thresholding of raw OPAL image

# Define ('central') photon energy bandwidth for plotting projected spectrum
# Andre thought maybe 2 eV bandwidth
min_cent_pe=0. # in eV
max_cent_pe=9999. # in eV

# Define lower and upper bounds of region of interest to monitor counts in
region_int_lower=600.6 #in eV
region_int_upper=700.14 #in eV

# Define parameters for L3 photon energy histogram 
minhistlim_L3PhotEnergy=500 #in eV
maxhistlim_L3PhotEnergy=560 #in eV
numbins_L3PhotEnergy=20

# Define parameters for FEE Gas Energy histogram 
minhistlim_FeeGasEnergy=0 # in mJ
maxhistlim_FeeGasEnergy=2 # in mJ
numbins_FeeGasEnergy=10

# Define parameters for FEE Gas Energy/ROI Counts 2D histogram
numbins_FGE_Counts_FGE=10
minhistlim_FGE_Counts_FGE=0
maxhistlim_FGE_Counts_FGE=2
numbins_FGE_Counts_Counts=20
minhistlim_FGE_Counts_Counts=0
maxhistlim_FGE_Counts_Counts=50

# Other parameters
history_len=1000
history_len_counts=1000 # different history length for plotting the estimated counts

refresh_rate=10 #plot every n frames

#%% For arcing warning
arc_freeze_time=0.2 # how many seconds to freeze plotting after arcing warning?

# For FEE Gas detector
fee_gas_threshold=0.0 #in mJ

#%% Now run
quot,rem=divmod(history_len, refresh_rate)
if rem!=0:
    history_len=refresh_rate*quot+1
    print 'For efficient monitoring of acc sum require history_len divisible by \
    refresh_rate, set history_len to '+str(history_len)

# Initialise SHES processor
processor=SHESPreProcessor(threshold=threshold)
# Extract shape of arrays which SHES processor will return
_,j_len,i_len=processor.pers_trans_params #for specified x_len_param/y_len_param in SHESPreProcessor,
#PerspectiveTransform() returns array of shape (y_len_param,x_len_param)
count_conv=processor.count_conv
calib_array=processor.calib_array
# Find indices for monitoring region of interest
region_int_idx_lower, region_int_idx_upper = \
(np.abs(calib_array-region_int_lower)).argmin(), (np.abs(calib_array-region_int_upper)).argmin()

region_int_lower_act, region_int_upper_act=calib_array[region_int_idx_lower], calib_array[region_int_idx_upper]
# actual bounds for region being monitored
print 'Monitoring counts in region between ' +str(np.round(region_int_lower_act,2))+\
      ' eV - '+str(np.round(region_int_upper_act,2))+' eV'

# Initialise L3 ebeam energy processor
l3Proc=L3EnergyProcessor()
# Initialise FEE  Gas processor
feeGas=FEEGasProcessor()

# Other initialisation
image_buff=np.zeros((refresh_rate, i_len, j_len)) # this gets reset to 0
x_proj_buff=np.zeros((refresh_rate, j_len)) # this gets reset to 0

counts_buff=np.zeros((refresh_rate,2)) # this gets reset to 0.
counts_buff_regint=np.zeros((refresh_rate,2)) # this gets reset to 0.

hist_L3PhotEnergy = Histogram((numbins_L3PhotEnergy,minhistlim_L3PhotEnergy,maxhistlim_L3PhotEnergy))
hist_FeeGasEnergy = Histogram((numbins_FeeGasEnergy,minhistlim_FeeGasEnergy,maxhistlim_FeeGasEnergy))
hist_FeeGasEnergy_CountsROI = Histogram((numbins_FGE_Counts_FGE,minhistlim_FGE_Counts_FGE,maxhistlim_FGE_Counts_FGE),\
                              numbins_FGE_Counts_Counts,minhistlim_FGE_Counts_Counts,maxhistlim_FGE_Counts_Counts))

if rank==0:
    publish.init() # initialise for plotting

    image_sum=np.zeros((i_len, j_len))
    x_proj_sum=np.zeros(j_len)

    image_sum_slice=np.zeros((i_len, j_len))
    x_proj_sum_slice=np.zeros(j_len)

    counts_buff_all=deque(maxlen=history_len_counts) # this doesn't get reset to 0
    counts_buff_regint_all=deque(maxlen=history_len_counts) # this doesn't get reset to 0. regint = region of 
    # interest, specified above
    image_sum_buff=deque(maxlen=1+history_len/refresh_rate)  # These keep the most recent one NOT to
    x_proj_sum_buff=deque(maxlen=1+history_len/refresh_rate) # be plotted so that it can be taken away
                                                             # from the rolling sum
    hist_L3PhotEnergy_all = np.zeros(numbins_L3PhotEnergy)
    hist_FeeGasEnergy_all = np.zeros(numbins_FeeGasEnergy) 
    hist_FeeGasEnergy_CountsROI_all = np.zeros((numbins_FGE_Counts_FGE, numbins_FGE_Counts_Counts))

    #%% Define plotting function
    def definePlots(x_proj_sum, image_sum, counts_buff, counts_buff_regint, opal_image, hist_L3PhotEnergy, \
                  hist_FeeGasEnergy, hist_FeeGasEnergy_CountsROI, nevt, numshotsforacc):
            # Define plots
            plotxproj = XYPlot(nevt,'Accumulated electron spectrum over past '+\
                    str(numshotsforacc)+' good shots', \
                    np.arange(x_proj_sum.shape[0]), x_proj_sum)
            plotcumimage = Image(nevt, 'Accumulated sum ('+str(numshotsforacc)+' good shots)', image_sum)
            plotcounts = XYPlot(nevt,'Estimated number of identified electron counts over past '+ \
                            str(len(counts_buff))+' good shots', np.arange(len(counts_buff)), \
                            np.array(counts_buff))
            plotcountsregint = XYPlot(nevt,'Estimated number of identified electron counts over past '+ \
                            str(len(counts_buff_regint))+' good shots in region '+str(np.round(region_int_lower_act,2))+\
                            ' eV - '+str(np.round(region_int_upper_act,2))+' eV (inclusive)', \
                            np.arange(len(counts_buff_regint)), np.array(counts_buff_regint))
            plotshot = Image(nevt, 'Single shot', opal_image)
            plotL3PhotEnergy = Hist(nevt,'Histogram of L3 \'central\' photon energies (plotting for '+str(np.round(min_cent_pe, 2))+\
            ' - '+str(np.round(max_cent_pe, 2))+')',  hist_L3PhotEnergy.edges[0], \
                           hist_L3PhotEnergy_all)
            plotFeeGasEnergy = Hist(nevt,'Histogram of FEE gas energy (plotting for above '+str(np.round(fee_gas_threshold, 2))+\
            ' only)',  hist_FeeGasEnergy.edges[0], hist_FeeGasEnergy_all)
            plotFeeGasEnergy_countsROI = Hist(nevt,'Histogram of FEE gas energy vs ROI ('#TODO') counts', hist_FeeGasEnergy_CountsROI) #TODO change edges here

            return plotxproj, plotcumimage, plotcounts, plotcountsregint, plotshot, plotL3PhotEnergy, plotFeeGasEnergy, plotfeeGasEnergy_Counts

    def sendPlots(x_proj_sum, image_sum, counts_buff, counts_buff_regint, opal_image, hist_L3PhotEnergy, \
                  hist_FeeGasEnergy, hist_FeeGasEnergy_CountsROI, nevt, numshotsforacc):
            plotxproj, plotcumimage, plotcounts, plotcountsregint, plotshot, plotL3PhotEnergy, plotFeeGasEnergy, \
            plotFeeGasEnergy_CountsROI=\
            definePlots(x_proj_sum, image_sum, counts_buff, counts_buff_regint, opal_image, hist_L3PhotEnergy, \
                  hist_FeeGasEnergy, hist_FeeGasEnergy_CountsROI, nevt, numshotsforacc)
            # Publish plots
            publish.send('AccElectronSpec', plotxproj)
            publish.send('OPALCameraAcc', plotcumimage)
            publish.send('ElectronCounts', plotcounts)
            publish.send('ElectronCountsRegInt', plotcountsregint)
            publish.send('OPALCameraSingShot', plotshot)
            publish.send('L3Histogram', plotL3PhotEnergy)
            publish.send('FEEGasHistogram', plotFeeGasEnergy)
            publish.send('FEEGasROICountsHistogram', plotFeeGasEnergy_CountsROI)

    def sendMultiPlot(x_proj_sum, image_sum, counts_buff, counts_buff_regint, opal_image, hist_L3PhotEnergy, \
                  hist_FeeGasEnergy, hist_FeeGasEnergy_CountsROI, nevt, numshotsforacc):
            plotxproj, plotcumimage, plotcounts, plotcountsregint, plotshot, plotL3PhotEnergy, plotFeeGasEnergy, \
            plotFeeGasEnergy_CountsROI=\
            definePlots(x_proj_sum, image_sum, counts_buff, counts_buff_regint, opal_image, hist_L3PhotEnergy, \
                  hist_FeeGasEnergy, hist_FeeGasEnergy_CountsROI, nevt, numshotsforacc)
            # Define multiplot
            multi = MultiPlot(nevt, 'SHES Online Monitoring', ncols=3)
            # Publish plots
            multi.add(plotshot)
            multi.add(plotcounts)
            multi.add(plotL3PhotEnergy)
            multi.add(plotcumimage)
            multi.add(plotcountsregint)            
            multi.add(plotFeeGasEnergy)
            multi.add(plotxproj)
            multi.add(plotFeeGasEnergy_Countshist_FeeGasEnergy_CountsROI)

            publish.send('SHES Online Monitoring', multi)

arcing_freeze=False
rolling_count=0
arc_time_ref=0.0 # will be set at certain number of seconds if required

# Now being looping over events
for nevt, evt in enumerate(ds.events()):
    if nevt%size!=rank: continue # each core only processes runs it needs
    fee_gas_energy=feeGas.ShotEnergy(evt)
    cent_pe=l3Proc.CentPE(evt)

    # Check data exists
    if fee_gas_energy is None:
        print 'No FEE gas energy, continuing to next event'        
        continue

    if cent_pe is None:
        print 'No L3 e-beam energy, continuing to next event'
        continue
    
    # If data exists, fill histograms
    hist_L3PhotEnergy.fill(cent_pe) 
    hist_FeeGasEnergy.fill(fee_gas_energy)

    #Check data falls within thresholds
    if fee_gas_energy < fee_gas_threshold:
        print 'FEE gas energy = '+str(fee_gas_energy)+' mJ -> continuing to next event'
        continue

    if not (cent_pe < max_cent_pe and cent_pe > min_cent_pe):
        print '\'Central\' photon energy = '+str(np.round(cent_pe,2))+\
        '-> outside specified range, skipping event'

    opal_image, x_proj, arced=processor.OnlineProcess(evt)

    if opal_image is None:
        print 'No SHES image, continuing to next event'
        continue

    if arced:
        print '***WARNING - ARC DETECTED!!!***'
        opal_image_copy=np.copy(opal_image)
        cv2.putText(opal_image_copy,'ARCING DETECTED!!!', \
        (50,int(i_len/2)), cv2.FONT_HERSHEY_SIMPLEX, 2, (255,0,0), 10)
        # Just send the single shot so you can see
        plotshot = Image(nevt, 'Single shot', opal_image_copy)
        publish.send('OPALCameraSingShot', plotshot)
#        arcing_freeze=True
#        arc_time_ref=time.time()

        continue # don't accumulate data for the arced shot
        
    image_buff[rolling_count]=opal_image
    x_proj_buff[rolling_count]=x_proj

    count_estimate=x_proj.sum()/float(count_conv) 
    counts_buff[rolling_count,0]=nevt; counts_buff[rolling_count,1]=count_estimate
    
    count_estimate_regint=x_proj[region_int_idx_lower:region_int_idx_upper+1].sum()/float(count_conv) 
    # this ignores the fact that the MCP display doesn't fill the entire OPAL array, which 
    # artificially decreases the integrated signal to count rate conversion factor (it divides the 
    # integrated signal) compared to the case where the array you are integrating over is entirely filled
    # by the MCP image, which is most likely the case for the region of interest 
    counts_buff_regint[rolling_count,0]=nevt; counts_buff_regint[rolling_count,1]=count_estimate_regint
    
    hist_FeeGasEnergy_CountsROI.fill(fee_gas_energy, count_estimate_regint)

    rolling_count+=1 #increment here

    if rolling_count==refresh_rate:

#        if arcing_freeze:
#            if (time.time()-arc_time_ref)>arc_freeze_time: arcing_freeze=False

        counts_buff_toappend=comm.gather(counts_buff, root=0)
        counts_buff_regint_toappend=comm.gather(counts_buff_regint, root=0)
        comm.Reduce(hist_L3PhotEnergy.values, hist_L3PhotEnergy_all, root=0) # array onto array
        comm.Reduce(hist_FeeGasEnergy.values, hist_FeeGasEnergy_all, root=0) # array onto array
        comm.Reduce(hist_FeeGasEnergy_CountsROI, hist_FeeGasEnergy_Counts_allROI, root=0) # TODO is this doing what I want

        # Reduce all the sums to the sum on the root core     
        comm.Reduce(image_buff.sum(axis=0), image_sum_slice, root=0)
        comm.Reduce(x_proj_buff.sum(axis=0), x_proj_sum_slice, root=0)
        #print image_buff.sum(axis=0).sum().sum()
        
        # Reset
        rolling_count=0

        image_buff=np.zeros((refresh_rate, i_len, j_len))
        x_proj_buff=np.zeros((refresh_rate, j_len))

        counts_buff=np.zeros((refresh_rate,2)) # reset to 0
        counts_buff_regint=np.zeros((refresh_rate,2)) # reset to 0

        if rank==0:
            # Only take away from the rolling sum if we have had more than the max history
            # length of shots
            image_sum_buff.append(image_sum_slice) 
            x_proj_sum_buff.append(x_proj_sum_slice)
          
            image_sum+=image_sum_slice
            x_proj_sum+=x_proj_sum_slice

            if len(x_proj_sum_buff)==x_proj_sum_buff.maxlen:
                #print 'hit max length' 
                image_sum-=image_sum_buff[0] # don't pop, let the deque with finite maxlen
                x_proj_sum-=x_proj_sum_buff[0] # take care of that itself
                numshotsforacc=(len(x_proj_sum_buff)-1)*refresh_rate
            else:
                numshotsforacc=len(x_proj_sum_buff)*refresh_rate

            image_sum_slice=np.zeros((i_len, j_len))
            x_proj_sum_slice=np.zeros(j_len)
            
            counts_buff_tosort=np.concatenate(counts_buff_toappend)
            counts_buff_all+=counts_buff_tosort[np.argsort(counts_buff_tosort[:,0])][:,1].tolist()
            # print counts_buff_tosort[np.argsort(counts_buff_tosort[:,0])][:,0].tolist()

            counts_buff_regint_tosort=np.concatenate(counts_buff_regint_toappend)
            counts_buff_regint_all+=counts_buff_regint_tosort[np.argsort(counts_buff_regint_tosort[:,0])][:,1].tolist()
             
#        if not arcing_freeze:
            sendMultiPlot(x_proj_sum, image_sum, counts_buff_all, counts_buff_regint_all, opal_image, hist_L3PhotEnergy_all, \
                          hist_FeeGasEnergy_all, hist_FeeGasEnergy_Counts_all, nevt, numshotsforacc)


        

        
