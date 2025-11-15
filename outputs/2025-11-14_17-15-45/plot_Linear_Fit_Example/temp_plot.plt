set encoding utf8
set terminal pngcairo size 800,600 font "Segoe UI,11"
unset title
set xlabel "X" font ",13"
set ylabel "Y" font ",13"
set xtics font ",11"
set ytics font ",11"
unset logscale x
unset logscale y
set format x
set format y
set grid back
unset key

set fit errorvariables
a = 5.0
b = 10.0

f(x) = a*x + b
fit f(x) "C:/Projects/Plotinator_10k/data/sample1.dat" using 1:2:3 via a,b

if (exists("a_err")) { print sprintf("PYFIT %s %0.16g %0.16g", "a", a, a_err) } else { print sprintf("PYFIT %s %0.16g %0.16g", "a", a, 0.0) }
if (exists("b_err")) { print sprintf("PYFIT %s %0.16g %0.16g", "b", b, b_err) } else { print sprintf("PYFIT %s %0.16g %0.16g", "b", b, 0.0) }

set output "C:/Projects/Plotinator_10k/outputs/2025-11-14_17-15-45/plot_Linear_Fit_Example/plot.png"
set multiplot layout 1,2 title "Linear Fit Example"
set encoding utf8
set title "Sample 1 (raw)" font ",16"
set xlabel "X" font ",13"
set ylabel "Y" font ",13"
set xtics font ",11"
set ytics font ",11"
unset logscale x
unset logscale y
set format x
set format y
set grid back
set key top right
plot "C:/Projects/Plotinator_10k/data/sample1.dat" using 1:2:3 with yerrorbars title "Sample 1 (raw)" pt 7 lw 2.0 lc rgb "blue", \
+     f(x) title sprintf("a*x + b") with lines lw 2.0 lc rgb "blue"
set encoding utf8
set title "Sample 1 (filtered)" font ",16"
set xlabel "X" font ",13"
set ylabel "Y" font ",13"
set xtics font ",11"
set ytics font ",11"
unset logscale x
unset logscale y
set format x
set format y
set grid back
set key top right
plot "C:/Projects/Plotinator_10k/outputs/2025-11-14_17-15-45/plot_Linear_Fit_Example/dataset_2/preprocessed.dat" using 1:2 with points title "Sample 1 (filtered)" pt 7 lc rgb "#ff7f0e", \
+     f(x) title sprintf("a*x + b") with lines lw 2.0 lc rgb "blue"
unset multiplot
unset output
