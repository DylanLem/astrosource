from astropy.io import fits
import numpy
import os
import glob
from .test_files import output_tests

from .comparison import find_comparisons, read_data_files, find_reference_frame

TEST_DATA_PATH = os.environ.get('AUTOVAR_TEST_DATA_PATH', os.path.join(os.getcwd(),'test_files'))

COMP_DATA_PATH = os.path.join(TEST_DATA_PATH, 'comparison')

def test_ensemble():
    fileCount = [ 2797858.97, 3020751.97, 3111426.77, 3115947.86]

def test_read_data_files():
    files = os.listdir(COMP_DATA_PATH)
    assert 'usedImages.txt' in files
    assert 'screenedComps.csv' in files
    assert 'targetstars.csv' in files
    compFile, photFileArray, fileList = read_data_files(COMP_DATA_PATH)
    referenceFrame, fileRaDec = find_reference_frame(photFileArray)
    assert list(referenceFrame[0]) == [154.7583434, -9.6660181000000005, 271.47230000000002, 23.331099999999999, 86656.100000000006, 319.22829999999999]
    assert (fileRaDec[0].ra.degree, fileRaDec[0].dec.degree) == ( 154.7583434,  -9.6660181)
    assert len(referenceFrame) == 227
    assert len(fileRaDec) == 227

def test_comparison():
    # All files are present so we are ready to continue
    outfile, num_cands = find_comparisons(COMP_DATA_PATH)

    assert outfile == os.path.join(COMP_DATA_PATH,"compsUsed.csv")
    assert num_cands == 11
