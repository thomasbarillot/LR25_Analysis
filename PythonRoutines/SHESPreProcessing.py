"""Pre-processing for the Scienta Hemispherical Analyser

Ended up copying all of the useful code from Andre into here because there were
too many processes being repeated in here and then in his find_blobs.py routines
"""
#%% Imports
from psana import *
import numpy as np
from scipy import ndimage
import cv2 # may be needed for the perspective transform that Andre does, don't
# know what is going on there yet

#%% These parameters hard-coded in

# Define detector
det_name='OPAL1' #TODO may need changing across beamtimes
countconv=10332.3985644 # from first 200 in "exp=AMO/amon0816:run=228:smd:dir=/reg/d/psdm/amo/amon0816/xtc:live", mean=10332.3985644 & stddev=1500.66170894

# Again may be needed for perspective transform, don't know what is going on yet
#pts1 = np.float32([[96,248],[935,193],[96,762],[935,785]])
#xLength = 839
#yLength = 591
#pts2 = np.float32([[0,0],[xLength,0],[0,yLength],[xLength,yLength]])
#M = cv2.getPerspectiveTransform(pts1,pts2)
#TODO figure out what the transforms are that we need from Andre
#TODO what do we do for sparking?

#%%

class SHESPreProcessor(object):

    def __init__(self, threshold=500., discard_border=1, \
                 poly_fit_params=None, \
                 perspective_transform=None):
        self.threshold=threshold
        self.discard_border=discard_border
        self.poly_fit_params=poly_fit_params
        self.perspective_transform=perspective_transform
        # And then this is hardcoded in already
        self.opal_det=Detector(det_name) # requires a
        # psana.DataSource instance to exist
        self.count_conv=10332.3985644

    def GetRawImg(self, event):
        return self.opal_det.raw(event)
        
    def DiscardBorder(self, opal_image):
        
        opal_image_cp=np.copy(opal_image)
        opal_image_cp[ :self.discard_border,:] = 0
        opal_image_cp[-self.discard_border:,:] = 0
        opal_image_cp[:, :self.discard_border] = 0
        opal_image_cp[:,-self.discard_border:] = 0
        
        return opal_image_cp

    def Threshold(self, opal_image):
        'Take greater than or equal to'
        return opal_image*self.Binary(opal_image) #TODO does this change the array in-place,
        #I think not
        
    def PerspectiveTransform(self, opal_image):
        return opal_image #TODO
    
    def PolyFit(self, opal_image):
        return opal_image #TODO
 
    def XProj(self, opal_image):    
        return opal_image.sum(axis=0) #TODO check this is the correct axis

    def Binary(self, opal_image):
        return opal_image>self.threshold
    
    def FindComs(self, opal_image):
        'Find the center of all blobs above threshold'
        binary = self.Binary(opal_image)
    
        labelled, num_labels = ndimage.label(binary)
        centers = ndimage.measurements.center_of_mass(binary, 
                                                  labelled,
                                                  range(1,num_labels+1))
        return centers, labelled

    def FindBlobs(self, opal_image):

        centers, labelled = self.FindComs(opal_image)

        widths = []
        for i in range(len(centers)):
        
            c = centers[i]
            r_slice = labelled[int(c[0]),:]
            zx = np.where( np.abs(r_slice - np.roll(r_slice, 1)) == i+1 )[0]
        
            c_slice = labelled[:,int(c[1])]
            zy = np.where( np.abs(c_slice - np.roll(c_slice, 1)) == i+1 )[0]
        
        
            if not (len(zx) == 2) or not (len(zy) == 2):
                #print "WARNING: Peak algorithm confused about width of peak at", c
                #print "         Setting default peak width (5,5)"
                widths.append( (5.0, 5.0) )
            else:
                x_width = zx[1] - zx[0]
                y_width = zy[1] - zy[0]
                widths.append( (x_width, y_width) )
        
        return centers, widths

    def PreProcess(self, event):  
        'This is the standard pre-processing for the SHES OPAL arrays'
        opal_image=self.GetRawImg(event)
        if opal_image is None:
            return np.nan, np.nan, np.nan
        opal_image=np.copy(opal_image)# makes a copy because
        # Detector.raw(evt) returns a read-only array for
        # obvious reasons
        opal_image=self.PolyFit(opal_image) # Thomas thinks the polynominal 
        # fit will take care of the perspective transform
        opal_image=self.DiscardBorder(opal_image)
        xs, ys=zip(*self.FindComs(opal_image)[0])
        x_proj=self.XProj(self.Threshold(opal_image))  

        return list(xs), list(ys), x_proj

    def OnlineProcess(self, event):  
        'This is the standard online processing for the SHES OPAL arrays'
        opal_image=self.GetRawImg(event)
        if opal_image is None:
            return None, None, None # returns NoneType
        opal_image=np.copy(opal_image)# makes a copy because
        # Detector.raw(evt) returns a read-only array for
        # obvious reasons
        opal_image=self.PolyFit(opal_image) # Thomas thinks the polynominal
        # fit will take care of the perspective transform
        opal_image=self.Threshold(self.DiscardBorder(opal_image))

        x_proj=self.XProj(opal_image)
        count_estimate=opal_image.sum().sum()/float(self.count_conv)
        
        return opal_image, x_proj, count_estimate





