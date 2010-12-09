#!/usr/bin/env python

import optparse, os, shutil, subprocess, sys, tempfile

def stop_err( msg ):
    sys.stderr.write( '%s\n' % msg )
    sys.exit()

# Copied from sam_to_bam.py:
def check_seq_file( dbkey, cached_seqs_pointer_file ):
    seq_path = ''
    for line in open( cached_seqs_pointer_file ):
        line = line.rstrip( '\r\n' )
        if line and not line.startswith( '#' ) and line.startswith( 'index' ):
            fields = line.split( '\t' )
            if len( fields ) < 3:
                continue
            if fields[1] == dbkey:
                seq_path = fields[2].strip()
                break
    return seq_path

def __main__():
    #Parse Command Line
    parser = optparse.OptionParser()
    parser.add_option( '-r', dest='ref_annotation', help='An optional "reference" annotation GTF. Each sample is matched against this file, and sample isoforms are tagged as overlapping, matching, or novel where appropriate. See the refmap and tmap output file descriptions below.' )
    parser.add_option( '-R', action="store_true", dest='ignore_nonoverlap', help='If -r was specified, this option causes cuffcompare to ignore reference transcripts that are not overlapped by any transcript in one of cuff1.gtf,...,cuffN.gtf. Useful for ignoring annotated transcripts that are not present in your RNA-Seq samples and thus adjusting the "sensitivity" calculation in the accuracy report written in the transcripts accuracy file' )
    parser.add_option( '-s', dest='use_seq_data', action="store_true", help='Causes cuffcompare to look into for fasta files with the underlying genomic sequences (one file per contig) against which your reads were aligned for some optional classification functions. For example, Cufflinks transcripts consisting mostly of lower-case bases are classified as repeats. Note that <seq_dir> must contain one fasta file per reference chromosome, and each file must be named after the chromosome, and have a .fa or .fasta extension.')
    
    # Wrapper / Galaxy options.
    parser.add_option( '-1', dest='input1')
    parser.add_option( '-2', dest='input2')
    parser.add_option( '', '--dbkey', dest='dbkey', help='The build of the reference dataset' )
    parser.add_option( '', '--index_dir', dest='index_dir', help='GALAXY_DATA_INDEX_DIR' )
    parser.add_option( '', '--ref_file', dest='ref_file', help='The reference dataset from the history' )
    parser.add_option( '-A', '--transcripts-accuracy-output', dest='transcripts_accuracy_output_file', help='' )
    parser.add_option( '-B', '--transcripts-combined-output', dest='transcripts_combined_output_file', help='' )
    parser.add_option( '-C', '--transcripts-tracking-output', dest='transcripts_tracking_output_file', help='' )
    parser.add_option( '', '--input1-tmap-output', dest='input1_tmap_output_file', help='' )
    parser.add_option( '', '--input1-refmap-output', dest='input1_refmap_output_file', help='' )
    parser.add_option( '', '--input2-tmap-output', dest='input2_tmap_output_file', help='' )
    parser.add_option( '', '--input2-refmap-output', dest='input2_refmap_output_file', help='' )
    
    (options, args) = parser.parse_args()
    
    # output version # of tool
    try:
        tmp = tempfile.NamedTemporaryFile().name
        tmp_stdout = open( tmp, 'wb' )
        proc = subprocess.Popen( args='cuffcompare 2>&1', shell=True, stdout=tmp_stdout )
        tmp_stdout.close()
        returncode = proc.wait()
        stdout = None
        for line in open( tmp_stdout.name, 'rb' ):
            if line.lower().find( 'cuffcompare v' ) >= 0:
                stdout = line.strip()
                break
        if stdout:
            sys.stdout.write( '%s\n' % stdout )
        else:
            raise Exception
    except:
        sys.stdout.write( 'Could not determine Cuffcompare version\n' )
        
    # Make temp directory for output.
    tmp_output_dir = tempfile.mkdtemp()
        
    # Set/link to sequence file.
    if options.use_seq_data:
        cached_seqs_pointer_file = os.path.join( options.index_dir, 'sam_fa_indices.loc' )
        if not os.path.exists( cached_seqs_pointer_file ):
            stop_err( 'The required file (%s) does not exist.' % cached_seqs_pointer_file )
        # If found for the dbkey, seq_path will look something like /galaxy/data/equCab2/sam_index/equCab2.fa,
        # and the equCab2.fa file will contain fasta sequences.
        seq_path = check_seq_file( options.dbkey, cached_seqs_pointer_file )
        if options.ref_file != 'None':
            # Create symbolic link to ref_file so that index will be created in working directory.
            seq_path = os.path.join( tmp_output_dir, "ref.fa" )
            os.symlink( options.ref_file, seq_path  )
    
    # Build command.
    
    # Base.
    cmd = "cuffcompare -o cc_output"
    
    # Add options.
    if options.ref_annotation:
        cmd += " -r %s" % options.ref_annotation
    if options.ignore_nonoverlap:
        cmd += " -R "
    if options.use_seq_data:
        cmd += " -s %s " % seq_path
        
    # Add input files.
        
    # Need to symlink inputs so that output files are written to temp directory. 
    # Also need an extension for input file names so that cuffcompare produces
    # output files properly.
    input1_file_name = os.path.join( tmp_output_dir, "input1.gtf" )
    os.symlink( options.input1,  input1_file_name )
    cmd += " %s" % input1_file_name
    two_inputs = ( options.input2 != None)
    if two_inputs:
        input2_file_name = os.path.join( tmp_output_dir, "input2.gtf" )
        os.symlink( options.input2, input2_file_name )
        cmd += " %s" % input2_file_name
        
    # Debugging.
    # print cmd
    
    # Run command.
    try:        
        tmp_name = tempfile.NamedTemporaryFile( dir=tmp_output_dir ).name
        tmp_stderr = open( tmp_name, 'wb' )
        proc = subprocess.Popen( args=cmd, shell=True, cwd=tmp_output_dir, stderr=tmp_stderr.fileno() )
        returncode = proc.wait()
        tmp_stderr.close()
        
        # Get stderr, allowing for case where it's very large.
        tmp_stderr = open( tmp_name, 'rb' )
        stderr = ''
        buffsize = 1048576
        try:
            while True:
                stderr += tmp_stderr.read( buffsize )
                if not stderr or len( stderr ) % buffsize != 0:
                    break
        except OverflowError:
            pass
        tmp_stderr.close()
        
        # Error checking.
        if returncode != 0:
            raise Exception, stderr
            
        # check that there are results in the output file
        cc_output_fname = os.path.join( tmp_output_dir, "cc_output")
        if len( open( cc_output_fname, 'rb' ).read().strip() ) == 0:
            raise Exception, 'The main output file is empty, there may be an error with your input file or settings.'
    except Exception, e:
        stop_err( 'Error running cuffcompare. ' + str( e ) )
        
    # Copy output files from tmp directory to specified files.
    try:
        try:
            shutil.copyfile( os.path.join( tmp_output_dir, "cc_output" ), options.transcripts_accuracy_output_file )
            shutil.copyfile( os.path.join( tmp_output_dir, "input1.tmap" ), options.input1_tmap_output_file )
            shutil.copyfile( os.path.join( tmp_output_dir, "input1.refmap" ), options.input1_refmap_output_file )
            shutil.copyfile( os.path.join( tmp_output_dir, "cc_output.combined.gtf" ), options.transcripts_combined_output_file )
            if two_inputs:
                shutil.copyfile( os.path.join( tmp_output_dir, "cc_output.tracking" ), options.transcripts_tracking_output_file )
                shutil.copyfile( os.path.join( tmp_output_dir, "input2.tmap" ), options.input2_tmap_output_file )
                shutil.copyfile( os.path.join( tmp_output_dir, "input2.refmap" ), options.input2_refmap_output_file )
        except Exception, e:
            stop_err( 'Error in cuffcompare:\n' + str( e ) ) 
    finally:
        # Clean up temp dirs
        if not os.path.exists( tmp_output_dir ):
            shutil.rmtree( tmp_output_dir )

if __name__=="__main__": __main__()
