#!/usr/bin/env python
# coding: utf-8

import os
import glob
import re
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.ticker import FuncFormatter
import seaborn as sns
import pyranges as pr
import pysam
import time

class Reports:
    data_table = None
    frag_hist = None
    frag_violin = None
    frag_bin500 = None
    seacr_beds = None
    bams = None

    def __init__(self, logger, meta, raw_frags, bin_frag, seacr_bed, bams):
        self.logger = logger
        self.meta_path = meta
        self.raw_frag_path = raw_frags
        self.bin_frag_path = bin_frag
        self.seacr_bed_path = seacr_bed
        self.bam_path = bams

        sns.set()
        sns.set_theme()
        sns.set_context("paper")

    #*
    #========================================================================================
    # UTIL
    #========================================================================================
    #*/

    def format_millions(self, x, pos):
        #the two args are the value and tick position
        return '%1.1fM' % (x * 1e-6)

    def format_thousands(self, x, pos):
        #the two args are the value and tick position
        return '%1.1fK' % (x * 1e-3)

    #*
    #========================================================================================
    # LOAD DATA
    #========================================================================================
    #*/

    def load_data(self):
        # ---------- Data - data_table --------- #
        self.data_table = pd.read_csv(self.meta_path, sep=',')
        self.duplicate_info = False
        if 'dedup_percent_duplication' in self.data_table.columns:
            self.duplicate_info = True

        # ---------- Data - Raw frag histogram --------- #
        # Create list of deeptools raw fragment files
        dt_frag_list = glob.glob(self.raw_frag_path)


        for i in list(range(len(dt_frag_list))):
            # create dataframe from csv file for each file and save to a list
            dt_frag_i = pd.read_csv(dt_frag_list[i], sep='\t', header=None, names=['Size','Occurrences'])
            frag_base_i = os.path.basename(dt_frag_list[i])
            sample_id = frag_base_i.split(".")[0]
            sample_id_split = sample_id.rsplit("_", 1)
            rep_i = sample_id_split[1]
            group_i = sample_id_split[0]

            # create long forms of fragment histograms
            dt_frag_i_long = np.repeat(dt_frag_i['Size'].values, dt_frag_i['Occurrences'].values)
            dt_group_i_long = np.repeat(group_i, len(dt_frag_i_long))
            dt_rep_i_long = np.repeat(rep_i, len(dt_frag_i_long))

            dt_group_i_short = np.repeat(group_i, dt_frag_i.shape[0])
            dt_rep_i_short = np.repeat(rep_i, dt_frag_i.shape[0])

            if i==0:
                frags_arr = dt_frag_i_long
                group_arr = dt_group_i_long
                rep_arr = dt_rep_i_long

                group_short = dt_group_i_short
                rep_short = dt_rep_i_short
                self.frag_hist = dt_frag_i
            else:
                frags_arr = np.append(frags_arr, dt_frag_i_long)
                group_arr = np.append(group_arr, dt_group_i_long)
                rep_arr = np.append(rep_arr, dt_rep_i_long)

                group_short = np.append(group_short, dt_group_i_short)
                rep_short = np.append(rep_short, dt_rep_i_short)
                self.frag_hist = self.frag_hist.append(dt_frag_i)

        self.frag_hist['group'] = group_short
        self.frag_hist['replicate'] = rep_short
        self.frag_violin = pd.DataFrame( { "fragment_size" : frags_arr, "group" : group_arr , "replicate": rep_arr} ) #, index = np.arange(len(frags_arr)))

        # ---------- Data - Binned frags --------- #
        # create full join data frame for count data
        # start by creating list of bin500 files
        dt_bin_frag_list = glob.glob(self.bin_frag_path)
        for i in list(range(len(dt_bin_frag_list))):
            dt_bin_frag_i_read = pd.read_csv(dt_bin_frag_list[i], sep='\t', header=None, names=['chrom','bin','count','sample'])
            sample_name = dt_bin_frag_i_read['sample'].iloc[0].split(".")[0]
            dt_bin_frag_i = dt_bin_frag_i_read[['chrom','bin','count']]
            dt_bin_frag_i.columns = ['chrom','bin',sample_name]

            if i==0:
                self.frag_bin500 = dt_bin_frag_i

            else:
                self.frag_bin500 = pd.merge(self.frag_bin500, dt_bin_frag_i, on=['chrom','bin'], how='outer')

        # add log2 transformed count data column
        log2_counts = self.frag_bin500[self.frag_bin500.columns[-(len(dt_bin_frag_list)):]].transform(lambda x: np.log2(x))
        chrom_bin_cols = self.frag_bin500[['chrom','bin']]
        self.frag_bin500 = pd.concat([chrom_bin_cols,log2_counts], axis=1)

        # ---------- Data - Peaks --------- #
        # create dataframe for seacr peaks
        seacr_bed_list = glob.glob(self.seacr_bed_path)

        # combine all seacr bed files into one df including group and replicate info
        for i in list(range(len(seacr_bed_list))):
            seacr_bed_i = pd.read_csv(seacr_bed_list[i], sep='\t', header=None, usecols=[0,1,2,3,4], names=['chrom','start','end','total_signal','max_signal'])
            bed_base_i = os.path.basename(seacr_bed_list[i])
            sample_id = bed_base_i.split(".")[0]
            sample_id_split = sample_id.rsplit("_", 1)
            rep_i = sample_id_split[1]
            group_i = sample_id_split[0]
            seacr_bed_i['group'] = np.repeat(group_i, seacr_bed_i.shape[0])
            seacr_bed_i['replicate'] = np.repeat(rep_i, seacr_bed_i.shape[0])

            if i==0:
                self.seacr_beds = seacr_bed_i

            else:
                self.seacr_beds = self.seacr_beds.append(seacr_bed_i)

        # ---------- Data - target histone mark bams --------- #
        bam_list = glob.glob(self.bam_path)
        self.bam_df_list = list()
        self.frip = pd.DataFrame(data=None, index=range(len(bam_list)), columns=['group','replicate','mapped_frags','frags_in_peaks','percentage_frags_in_peaks'])
        k = 0 #counter

        def pe_bam_to_df(bam_path):
            bamfile = pysam.AlignmentFile(bam_path, "rb")
            # Iterate through reads.
            read1 = None
            read2 = None
            k=0 #counter

            # get number of reads in bam
            count = 0
            for _ in bamfile:
                count += 1

            bamfile.close()
            bamfile = pysam.AlignmentFile(bam_path, "rb")

            # initialise arrays
            frag_no = round(count/2)
            start_arr = np.zeros(frag_no, dtype=np.int64)
            end_arr = np.zeros(frag_no, dtype=np.int64)
            chrom_arr = np.empty(frag_no, dtype="<U20")

            for read in bamfile:

                if not read.is_paired or read.mate_is_unmapped or read.is_duplicate:
                    continue

                if read.is_read2:
                    read2 = read
                    # print("is read2: " + read.query_name)

                else:
                    read1 = read
                    read2 = None
                    # print("is read1: " + read.query_name)

                if read1 is not None and read2 is not None and read1.query_name == read2.query_name:

                    start_pos = min(read1.reference_start, read2.reference_start)
                    end_pos = max(read1.reference_end, read2.reference_end) - 1
                    chrom = read.reference_name

                    start_arr[k] = start_pos
                    end_arr[k] = end_pos
                    chrom_arr[k] = chrom

                    k +=1

            bamfile.close()

            # remove zeros and empty elements. The indicies for these are always the same from end_arr and chrom_arr
            remove_idx = np.where(chrom_arr == '')[0]
            chrom_arr = np.delete(chrom_arr, remove_idx)
            start_arr = np.delete(start_arr, remove_idx)
            end_arr = np.delete(end_arr, remove_idx)

            # create dataframe
            bam_df = pd.DataFrame({ "Chromosome" : chrom_arr, "Start" : start_arr, "End" : end_arr })
            return(bam_df)

        for bam in bam_list:
            bam_now = pe_bam_to_df(bam)
            self.bam_df_list.append(bam_now)
            bam_base = os.path.basename(bam)
            sample_id = bam_base.split(".")[0]
            [group_now,rep_now] = sample_id.rsplit("_", 1)
            self.frip.at[k, 'group'] = group_now
            self.frip.at[k, 'replicate'] = rep_now
            self.frip.at[k, 'mapped_frags'] = bam_now.shape[0]
            k=k+1

        # ---------- Data - New frag_hist --------- #
        for i in list(range(len(self.bam_df_list))):
            df_i = self.bam_df_list[i]
            widths_i = (df_i['End'] - df_i['Start']).abs()
            unique_i, counts_i = np.unique(widths_i, return_counts=True)
            group_i = np.repeat(self.frip.at[i, 'group'], len(unique_i))
            rep_i = np.repeat(self.frip.at[i, 'replicate'], len(unique_i))

            if i==0:
                frag_lens = unique_i
                frag_counts = counts_i
                group_arr = group_i
                rep_arr = rep_i
            else:
                frag_lens = np.append(frag_lens, unique_i)
                frag_counts = np.append(frag_counts, counts_i)
                group_arr = np.append(group_arr, group_i)
                rep_arr = np.append(rep_arr, rep_i)

        self.frag_series = pd.DataFrame({'group' : group_arr, 'replicate' : rep_arr, 'frag_len' : frag_lens, 'occurences' : frag_counts})

        # ---------- Data - Peak stats --------- #
        self.seacr_beds_group_rep = self.seacr_beds[['group','replicate']].groupby(['group','replicate']).size().reset_index().rename(columns={0:'all_peaks'})

        # ---------- Data - Reproducibility of peaks between replicates --------- #
        # empty dataframe to fill in loop
        self.reprod_peak_stats = self.seacr_beds_group_rep #self.df_no_peaks
        self.reprod_peak_stats = self.reprod_peak_stats.reindex(columns=self.reprod_peak_stats.columns.tolist() + ['no_peaks_reproduced','peak_reproduced_rate'])

        # create permutations list
        def array_permutate(x):
            arr_len=len(x)
            loop_list = x
            out_list = x
            for i in range(arr_len-1):
                i_list = np.roll(loop_list, -1)
                out_list = np.vstack((out_list, i_list))
                loop_list = i_list
            return out_list

        # create pyranges objects and fill df
        unique_groups = self.seacr_beds.group.unique()
        unique_replicates = self.seacr_beds.replicate.unique()
        self.replicate_number = 1
        self.multiple_reps = True
        if (len(unique_groups) == self.seacr_beds_group_rep.shape[0]):
            self.multiple_reps = False

        if self.multiple_reps:
            idx_count=0
            for i in list(range(len(unique_groups))):
                group_i = unique_groups[i]
                group_reps = len(self.seacr_beds_group_rep[self.seacr_beds_group_rep['group'] == group_i])
                if group_reps < 2:
                    continue
                rep_permutations = array_permutate(range(group_reps))
                for k in list(range(group_reps)):
                    pyr_query = pr.PyRanges()
                    rep_perm = rep_permutations[k]
                    for j in rep_perm:
                        rep_i = "R" + str(range(group_reps)[j]+1)
                        peaks_i = self.seacr_beds[(self.seacr_beds['group']==group_i) & (self.seacr_beds['replicate']==rep_i)]
                        pyr_subject = pr.PyRanges(chromosomes=peaks_i['chrom'], starts=peaks_i['start'], ends=peaks_i['end'])
                        if(len(pyr_query) > 0):
                            pyr_overlap = pyr_query.join(pyr_subject)
                            pyr_overlap = pyr_overlap.apply(lambda df: df.drop(['Start_b','End_b'], axis=1))
                            pyr_query = pyr_overlap

                        else:
                            pyr_query = pyr_subject

                    if (pyr_query.empty):
                        self.reprod_peak_stats.at[idx_count, 'no_peaks_reproduced'] = 0

                    else :
                        pyr_starts = pyr_query.values()[0]['Start']
                        unique_pyr_starts = pyr_starts.unique()
                        self.reprod_peak_stats.at[idx_count, 'no_peaks_reproduced'] = len(unique_pyr_starts)

                    idx_count = idx_count + 1

            fill_reprod_rate = (self.reprod_peak_stats['no_peaks_reproduced'] / self.reprod_peak_stats['all_peaks'])*100
            self.reprod_peak_stats['peak_reproduced_rate'] = fill_reprod_rate

        # ---------- Data - Percentage of fragments in peaks --------- #
        for i in range(len(self.bam_df_list)):
            bam_i = self.bam_df_list[i]
            self.frip.at[i,'mapped_frags'] = bam_i.shape[0]
            group_i = self.frip.at[i,'group']
            rep_i = self.frip.at[i,'replicate']
            seacr_bed_i = self.seacr_beds[(self.seacr_beds['group']==group_i) & (self.seacr_beds['replicate']==rep_i)]
            pyr_seacr = pr.PyRanges(chromosomes=seacr_bed_i['chrom'], starts=seacr_bed_i['start'], ends=seacr_bed_i['end'])
            pyr_bam = pr.PyRanges(df=bam_i)
            sample_id = group_i + "_" + rep_i
            frag_count_pyr = pyr_bam.count_overlaps(pyr_seacr)
            frag_counts = np.count_nonzero(frag_count_pyr.NumberOverlaps)

            self.frip.at[i,'frags_in_peaks'] = frag_counts

        self.frip['percentage_frags_in_peaks'] = (self.frip['frags_in_peaks'] / self.frip['mapped_frags'])*100

    def annotate_data_table(self):
        # Make new perctenage alignment columns
        self.data_table['target_alignment_rate'] = self.data_table.loc[:, ('bt2_total_aligned_target')] / self.data_table.loc[:, ('bt2_total_reads_target')] * 100
        self.data_table['spikein_alignment_rate'] = self.data_table.loc[:, ('bt2_total_aligned_spikein')] / self.data_table.loc[:, ('bt2_total_reads_spikein')] * 100

    #*
    #========================================================================================
    # GEN REPORTS
    #========================================================================================
    #*/

    def generate_plots(self):
        # Init
        plots = dict()
        data = dict()

        # Get Data
        self.load_data()
        self.annotate_data_table()

        # Plot 1
        multi_plot, data1 = self.alignment_summary()
        plots["01_01_seq_depth"] = multi_plot[0]
        plots["01_02_alignable_frag"] = multi_plot[1]
        plots["01_03_alignment_rate_target"] = multi_plot[2]
        plots["01_04_alignment_rate_spikein"] = multi_plot[3]
        data["01_alignment_summary"] = data1

        # Plot 2
        if self.duplicate_info == True:
            multi_plot, data2 = self.duplication_summary()
            plots["02_01_dup_rate"] = multi_plot[0]
            plots["02_02_est_lib_size"] = multi_plot[1]
            plots["02_03_unique_frags"] = multi_plot[2]
            data["02_duplication_summary"] = data2

        # Plot 3
        plot3, data3 = self.fraglen_summary_violin()
        plots["03_01_frag_len_violin"] = plot3
        data["03_01_frag_len_violin"] = data3

        # Plot 4
        plot4, data4 = self.fraglen_summary_histogram()
        plots["03_02_frag_len_hist"] = plot4
        data["03_02_frag_len_hist"] = data4

        # Plot 5
        plot5, data5 = self.replicate_heatmap()
        plots["04_replicate_heatmap"] = plot5
        data["04_replicate_heatmap"] = data5

        # Plot 6
        multi_plot, data6 = self.scale_factor_summary()
        plots["05_01_scale_factor"] = multi_plot[0]
        plots["05_02_frag_count"] = multi_plot[1]
        data["05_scale_factor_summary"] = data6

        # Plot 7a
        plot7a, data7a = self.no_of_peaks()
        plots["06_01_no_of_peaks"] = plot7a
        data["06_01_no_of_peaks"] = data7a

        # Plot 7b
        plot7b, data7b = self.peak_widths()
        plots["06_02_peak_widths"] = plot7b
        data["06_02_peak_widths"] = data7b

        # Plot 7c
        if self.multiple_reps:
            plot7c, data7c = self.reproduced_peaks()
            plots["06_03_reproduced_peaks"] = plot7c
            data["06_03_reproduced_peaks"] = data7c

        # Plot 7d
        plot7d, data7d = self.frags_in_peaks()
        plots["06_04_frags_in_peaks"] = plot7d
        data["06_04_frags_in_peaks"] = data7d

        # Fragment Length Histogram data in MultiQC yaml format
        txt = self.frag_len_hist_mqc()

        return (plots, data, txt)

    def gen_plots_to_folder(self, output_path):
        # Init
        abs_path = os.path.abspath(output_path)

        # Get plots and supporting data tables
        plots, data, txt = self.generate_plots()

        # Save mqc text file
        txt_mqc = open(os.path.join(abs_path, "03_03_frag_len_mqc.txt"), "w")
        txt_mqc.write(txt)
        txt_mqc.close()

        # Save data to output folder
        for key in data:
            data[key].to_csv(os.path.join(abs_path, key + '.csv'), index=False)

        # Save plots to output folder
        for key in plots:
            plots[key].savefig(os.path.join(abs_path, key + '.png'))

        # Save pdf of the plots
        self.gen_pdf(abs_path, plots)

    def gen_pdf(self, output_path, plots):
        with PdfPages(os.path.join(output_path, 'merged_report.pdf')) as pdf:
            for key in plots:
                pdf.savefig(plots[key])

    #*
    #========================================================================================
    # TXT FILES
    #========================================================================================
    #*/

    def frag_len_hist_mqc(self):
        size_list = self.frag_hist["Size"].to_numpy().astype(str)
        occurrences_list = self.frag_hist["Occurrences"].to_numpy().astype(str)
        size_list_sep = np.core.defchararray.add(size_list, " : ")
        x_y_list = np.core.defchararray.add(size_list_sep, occurrences_list)

        group_rep = self.frag_hist[['group','replicate']].groupby(['group','replicate']).size().reset_index()
        first_line = "data:"

        for i in list(range(group_rep.shape[0])):
            group_i = group_rep.at[i,"group"]
            rep_i = group_rep.at[i,"replicate"]
            str_list = x_y_list[ (self.frag_hist['group'] == group_i) & (self.frag_hist['replicate'] == rep_i) ]
            # print(str_list)

            x_y_str = ", ".join(str_list)
            full_line_i = "    '" + group_i + "_" + rep_i + "' : {" + x_y_str + "}"
            if i==0:
                frag_len_hist_mqc_dict = "\n".join([first_line, full_line_i])

            else:
                frag_len_hist_mqc_dict = "\n".join([frag_len_hist_mqc_dict, full_line_i])


        return frag_len_hist_mqc_dict

    #*
    #========================================================================================
    # PLOTS
    #========================================================================================
    #*/

    # ---------- Plot 1 - Alignment Summary --------- #
    def alignment_summary(self):
        sns.color_palette("magma", as_cmap=True)
        sns.set(font_scale=0.6)
        # Subset data
        df_data = self.data_table.loc[:, ('id', 'group', 'bt2_total_reads_target', 'bt2_total_aligned_target', 'target_alignment_rate', 'spikein_alignment_rate')]

        # Create plots array
        figs = []

        # Seq depth
        fig, ax = plt.subplots()
        ax = sns.boxplot(data=df_data, x='group', y='bt2_total_reads_target', palette = "magma")
        fig.suptitle("Sequencing Depth")
        ax.set(ylabel="Total Reads")
        figs.append(fig)

        # Alignable fragments
        fig, ax = plt.subplots()
        ax = sns.boxplot(data=df_data, x='group', y='bt2_total_aligned_target', palette = "magma")
        fig.suptitle("Alignable Fragments")
        ax.set(ylabel="Total Aligned Reads")
        figs.append(fig)

        # Alignment rate hg38
        fig, ax = plt.subplots()
        ax = sns.boxplot(data=df_data, x='group', y='target_alignment_rate', palette = "magma")
        fig.suptitle("Alignment Rate (Target)")
        ax.set(ylabel="Percent of Fragments Aligned")
        figs.append(fig)

        # Alignment rate e.coli
        fig, ax = plt.subplots()
        ax = sns.boxplot(data=df_data, x='group', y='spikein_alignment_rate', palette = "magma")
        fig.suptitle("Alignment Rate (Spike-in)")
        ax.set(ylabel="Percent of Fragments Aligned")
        figs.append(fig)

        return figs, df_data

    # ---------- Plot 2 - Duplication Summary --------- #
    def duplication_summary(self):
        # Init
        k_formatter = FuncFormatter(self.format_thousands)
        m_formatter = FuncFormatter(self.format_millions)

        # Subset data
        df_data = self.data_table.loc[:, ('id', 'group', 'dedup_percent_duplication', 'dedup_estimated_library_size', 'dedup_read_pairs_examined')]
        df_data['dedup_percent_duplication'] *= 100
        df_data['unique_frag_num'] = df_data['dedup_read_pairs_examined'] * (1-df_data['dedup_percent_duplication']/100)

        # Create plots array
        figs = []

        # Duplication rate
        fig, ax = plt.subplots()
        ax = sns.boxplot(data=df_data, x='group', y='dedup_percent_duplication', palette = "magma")
        fig.suptitle("Duplication Rate")
        ax.set(ylabel="Rate (%)")
        ax.set(ylim=(0, 100))
        ax.xaxis.set_tick_params(labelrotation=45)
        figs.append(fig)

        # Estimated library size
        fig, ax = plt.subplots()
        ax = sns.boxplot(data=df_data, x='group', y='dedup_estimated_library_size', palette = "magma")
        fig.suptitle("Estimated Library Size")
        ax.set(ylabel="Size")
        ax.yaxis.set_major_formatter(m_formatter)
        ax.xaxis.set_tick_params(labelrotation=45)
        figs.append(fig)

        # No. of unique fragments
        fig, ax = plt.subplots()
        ax = sns.boxplot(data=df_data, x='group', y='unique_frag_num', palette = "magma")
        fig.suptitle("Unique Fragments")
        ax.set(ylabel="Count")
        ax.yaxis.set_major_formatter(k_formatter)
        ax.xaxis.set_tick_params(labelrotation=45)
        figs.append(fig)

        return figs, df_data


    # ---------- Plot 3 - Fragment Distribution Violin --------- #
    def fraglen_summary_violin(self):
        fig, ax = plt.subplots()
        ax = sns.violinplot(data=self.frag_violin, x="group", y="fragment_size", hue="replicate", palette = "viridis")
        ax.set(ylabel="Fragment Size")
        fig.suptitle("Fragment Length Distribution")

        return fig, self.frag_violin

    # ---------- Plot 4 - Fragment Distribution Histogram --------- #
    def fraglen_summary_histogram(self):
        fig, ax = plt.subplots()
        # ax = sns.lineplot(data=self.frag_hist, x="Size", y="Occurrences", hue="Sample")
        ax = sns.lineplot(data=self.frag_hist, x="Size", y="Occurrences", hue="group", style="replicate", palette = "magma")
        fig.suptitle("Fragment Length Distribution")

        return fig, self.frag_hist

    def alignment_summary_ex(self):
        df_data = self.data_table.loc[:, ('id', 'group', 'bt2_total_reads_target', 'bt2_total_aligned_target', 'target_alignment_rate', 'spikein_alignment_rate')]

        ax = px.box(df_data, x="group", y="bt2_total_reads_target", palette = "magma")

        return ax, df_data


    # ---------- Plot 5 - Replicate Reproducibility Heatmap --------- #
    def replicate_heatmap(self):
        fig, ax = plt.subplots()
        plot_data = self.frag_bin500[self.frag_bin500.columns[-(len(self.frag_bin500.columns)-2):]]
        # plot_data = plot_data.fillna(0)
        corr_mat = plot_data.corr(method='pearson')
        ax = sns.heatmap(corr_mat, annot=True)
        fig.suptitle("Replicate Reproducibility")

        return fig, self.frag_bin500

    # ---------- Plot 6 - Scale Factor Comparison --------- #
    def scale_factor_summary(self):
        # Get normalised count data
        df_normalised_frags = self.data_table.loc[:, ('id', 'group')]
        df_normalised_frags['normalised_frags'] = self.data_table['bt2_total_reads_target']*self.data_table['scale_factor']

        figs = []

        # Subset meta data
        df_data_scale = self.data_table.loc[:, ('id', 'group','scale_factor')]

        # Scale factor
        fig, ax = plt.subplots()
        ax = sns.boxplot(data=df_data_scale, x='group', y='scale_factor', palette = "magma")
        fig.suptitle("Spike-in Scale Factor")
        ax.set(ylabel="Coefficient")
        figs.append(fig)

        # Normalised fragment count
        fig, ax = plt.subplots()
        ax = sns.boxplot(data=df_normalised_frags, x='group', y='normalised_frags', palette = "magma")
        fig.suptitle("Normalised Fragment Count")
        ax.set(ylabel="Count")
        figs.append(fig)

        return figs, df_data_scale

    # ---------- Plot 7 - Peak Analysis --------- #
    def no_of_peaks(self):
    # 7a - Number of peaks
        fig, ax = plt.subplots()
        fig.suptitle("Total Peaks")

        ax = sns.boxplot(data=self.seacr_beds_group_rep, x='group', y='all_peaks', palette = "magma")
        ax.set_ylabel("No. of Peaks")

        return fig, self.seacr_beds_group_rep

    # 7b - Width of peaks
    def peak_widths(self):
        fig, ax = plt.subplots()

        ## add peak width column
        self.seacr_beds['peak_width'] = self.seacr_beds['end'] - self.seacr_beds['start']
        self.seacr_beds['peak_width'] = self.seacr_beds['peak_width'].abs()

        ax = sns.violinplot(data=self.seacr_beds, x="group", y="peak_width", hue="replicate", palette = "viridis")
        ax.set_ylabel("Peak Width")
        fig.suptitle("Peak Width Distribution")

        return fig, self.seacr_beds


    # 7c - Peaks reproduced
    def reproduced_peaks(self):
        fig, ax = plt.subplots()

        # plot
        ax = sns.barplot(data=self.reprod_peak_stats, hue="replicate", x="group", y="peak_reproduced_rate", palette = "viridis")
        ax.set_ylabel("Peaks Reproduced (%)")
        fig.suptitle("Peak Reprodducibility")

        return fig, self.reprod_peak_stats

    # 7d - Fragments within peaks
    def frags_in_peaks(self):
        fig, ax = plt.subplots()

        ax = sns.boxplot(data=self.frip, x='group', y='percentage_frags_in_peaks', palette = "magma")
        ax.set_ylabel("Fragments within Peaks (%)")
        fig.suptitle("Aligned Fragments within Peaks")

        return fig, self.frip
