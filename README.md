# Unleashed-Sound-Manager
Developer: Digitzaki
Automatic hex data modification of Uber and Samp audio files within the 2007 Wii Game "Godzilla Unleashed" Made to make modding less tedious!

# How to use:
+ Get the audio files from dumping the iso, you can right click dolphin → properties → files and right click export the audio folder. For Revolution or any Riivolution mod in the future, it should be in load. In Revolution’s case look in the load/gunleashed folder.
+ Uber and Samp files MUST GO in the Extract folder.
+ browse for the export folder and select it, then press the “Export Now!” button.
+ This will export all dsp’s within the Extract folder. Use the provided Audacity with special plugins to edit the audio files.
+ When you are done make sure the sound is Mono, not Stereo. For best quality keep it the same length. When saving make sure it is a .dsp file, read the note below.
# Note
+ DO NOT SAVE OVER THE ORIGINAL DSP, PUT THEM IN THE PROVIDED OR YOUR OWN REIMPORT FOLDER!!!
# Reimporting
+ When completing the audio editing, and ensuring the edited dsp file names match their corresponding replacements, browse and add the re import folder and the export if you have not already
+ The code will sort through all sounds that have a match and do all the hex data work for you!
+ When this is done the samp and uber you had placed within the export folder will be updated! Rebuild the iso or place them within a Riivolution custom folder!
