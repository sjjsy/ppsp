# wip.md — Work in progress

Active specs, wireframes, brainstorming, and annotations for work currently in
flight. Not stable documentation.

Lifecycle: write here while working → annotate with TODO/FIXME/IDEA/QUESTION →
commit annotated state → revise → when shipped, commit final state then flush
content here and summarise into journal.md and possibly design.md.


## Improvements to the --name command and its addition to the interactive CLI and GUI flows
- When `ppsp -n` is launched without batch mode it asks whether a) to ask for names one-by-one in terminal or b) to write the ppsp_stacks.csv (with empty Title and Shorthand columns) and then open it with xdg-open for editing after which to extract any added names from it (as if that CSV was given as the CLI argument for the command in the first place). Any missing shorthands should be computed from the Title if unspecified.
- The Stack class instance should distinguish between types of photos in its folder. The primary photos in the stack are the raw photos (e.g. ARW, ORF). All other "photos" in that stack are derivatives. So the "Photos" count for the ppsp_stack.csv should reflect these primary photos, not the total number of image files in the folder. Please fix.
- Add a `Tags` and `Rating` column into the ppsp_stacks.csv before the `GenerateSpecs` column. Move the `Title` and `Shorthand` columns to be after the `Photos` column. Rename the `Photos` column to `RawPhotoCount`.
- After an interactive `ppsp -n` round or the ingestion of the CSV file from a CLI arg, any identified updates should be done.
- The tool should store a sidecar metadata file in the stack folder with the same name as the primary photo but with the .json suffix (assuming you agree JSON is a good format; Some tools favor .xmp with XML metadata). The sidecar should include the title, tags and rating information and those should be synced with the columns in the CSV and the actual EXIF/XMP tags of the files, such that those would be available also on third party photo management software.
- The sidecar metadata file helps in noticing which metadata was changed through the CSV edits and which remained the same, to avoid having to check and update the metadata from the images. The --cleanup command should not delete these metadata files even though the information is already embedded into the photo files as well.
- Both the CLI and GUI flows should include a metadata edit step between the stack culling and discovery steps.
- I notice models.py contains _KNOWN_TMOS, CTs and z-tier lists in the code as hard coded string lists. Please refactor those to use the definitions from variants.py such that information does not need to be duplicated and maintained in several places.
