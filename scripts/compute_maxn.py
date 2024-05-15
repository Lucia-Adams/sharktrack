from argparse import ArgumentParser
import pandas as pd
import os
from pathlib import Path
import click
import sys
import cv2
import traceback
sys.path.append("utils")
from image_processor import extract_frame_at_time, draw_bboxes
from time_processor import string_to_ms

def detection_is_unlabeled(d):
    return d.split(".")[0].isnumeric()

def get_maxn_confidence(labeled_detections):
    completed_annotations = 0
    for k, v in labeled_detections.items():
        if v:
            completed_annotations += 1

    return completed_annotations / len(labeled_detections)

def get_labeled_detections(output_path: str):
    predefined_output_csv = "output.csv"
    output_csv_path = os.path.join(output_path, predefined_output_csv)
    assert os.path.exists(output_csv_path), f"To clean annotations locally you must have './detections' folder in the output path but {output_csv_path} doesn't exist!"

    valid_detections = [f.name for f in Path(output_path).rglob("*jpg")]
    assert len(valid_detections) == len(set(valid_detections)), "Detections don't have unique (track_id, species)"

    labeled_detections = {}
    for d in valid_detections:
        if detection_is_unlabeled(d):
            labeled_detections[int(d.split(".")[0])] = None
        else:
            try:
                track_id = int(d.split("-")[0])
                label = d.split("-", maxsplit=1)[1].replace(".jpg", "")
                labeled_detections[track_id] = label
            except:
                raise Exception("All files in ./detections should be '{TRACK_ID}-{CLASS}.jpg' but there is failing file: " + d)

    return labeled_detections
    
def get_original_output(original_output_path):
    assert os.path.exists(original_output_path), f"No output.csv file found in {original_output_path}. output.csv represents the unclean output from sharktrack and is required to clean the annotations."
    return pd.read_csv(original_output_path)

def clean_annotations_locally(sharktrack_df, labeled_detections):
    filtered_sharktrack_df = sharktrack_df[sharktrack_df["track_id"].isin(labeled_detections.keys())]
    if len(filtered_sharktrack_df) == 0:
        print("output csv empty!")
        return
    filtered_sharktrack_df.loc[:, "label"] = filtered_sharktrack_df.apply((lambda row: labeled_detections[row.track_id] or row.label), axis=1)
    return filtered_sharktrack_df

def compute_species_max_n(cleaned_annotations):
    frame_box_cnt = cleaned_annotations.groupby(["video_path", "video_name", "frame", "label"], as_index=False).agg(time=("time", "first"), n=("track_id", "count"), tracks_in_maxn=("track_id", lambda x: list(x)))

    # for each chapter, species, get the max n and return video, species, maxn, chapter, time when that happens
    maxn = frame_box_cnt.sort_values("n", ascending=False).groupby(["video_path", "video_name", "label"], as_index=False).head(1)
    maxn = maxn.sort_values(["video_path", "n"], ascending=[True, False])
    maxn = maxn.reset_index(drop=True)

    return maxn

def save_maxn_frames(cleaned_output: pd.DataFrame, maxn: pd.DataFrame, videos_path: Path):
    for idx, row in maxn.iterrows():
        video_relative_path = row["video_path"]
        label = row["label"]
        video_path = videos_path / video_relative_path
        print(f"Extracting MaxN Frame for {video_path}, {label=}")
        try:
            time_ms = string_to_ms(row["time"])
            frame = extract_frame_at_time(str(video_path), time_ms)
            maxn_sightings = cleaned_output[(cleaned_output["time"] == row["time"]) & (cleaned_output["video_path"] == video_relative_path)]
            bboxes = maxn_sightings[["xmin", "ymin", "xmax", "ymax"]].values
            labels = maxn_sightings[["label"]].values
            plot = draw_bboxes(frame, bboxes, labels)
            cv2.imwrite(f"{label}{idx}.jpg", plot)
        except:
            traceback.print_exc()
            print(f"Failed reading video {video_path}. \n You provided video path {videos_path}, please make sure you provide only the root path that joins with relative path{video_relative_path}")
            return

@click.command()
@click.option("--path", "-p", type=str, required=True, prompt="Provide path to original output", help="Path to the output folder of sharktrack")
@click.option("--videos", "-v", type=str, default="N/A", show_default=True, prompt="Path to original videos (to compute maxn screenshots)", help="Path to the folder that contains all videos, to extract MaxN")
def main(path, videos):
    final_analysis_folder = "analysed"
    maxn_filename = "maxn.csv"

    if not os.path.exists(path):
        print(f"Output path {path} does not exist")
        return
    print(f"Computing MaxN from annotations cleaned locally...")
    original_output_path = os.path.join(path, "output.csv")
    original_output = get_original_output(original_output_path)
    labeled_detections = get_labeled_detections(path)
    maxn_confidence = get_maxn_confidence(labeled_detections)

    cleaned_annotations = clean_annotations_locally(original_output, labeled_detections)
    cleaned_annotations.to_csv(original_output_path)
    maxn = compute_species_max_n(cleaned_annotations)

    max_n_path = Path(path) / final_analysis_folder / maxn_filename
    max_n_path.parent.mkdir(exist_ok=True, parents=True)
    maxn.to_csv(str(max_n_path), index=False)
    print(f"MaxN computed! Check in the folder {max_n_path}")
    print(f"MaxN confidence achieved {int(maxn_confidence*100)}%")

    if videos == "N/A":
        # extract the frame from each maxn and annotate it with output.csv
        print("Provide the path to the original videos to compute MaxN screenshots")
    else:
        videos_path = Path(videos)
        save_maxn_frames(cleaned_annotations, maxn, videos_path)


if __name__ == "__main__":
    main()