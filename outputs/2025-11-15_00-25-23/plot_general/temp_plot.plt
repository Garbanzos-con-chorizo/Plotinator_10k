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
ax = 44.51
bx = 89.02
c = 133.53

f(x) = ax^2+bx+c
fit f(x) "C:/Projects/Plotinator_10k/data/sample3.dat" via ax,bx,c

if (exists("ax_err")) { print sprintf("PYFIT %s %0.16g %0.16g", "ax", ax, ax_err) } else { print sprintf("PYFIT %s %0.16g %0.16g", "ax", ax, 0.0) }
if (exists("bx_err")) { print sprintf("PYFIT %s %0.16g %0.16g", "bx", bx, bx_err) } else { print sprintf("PYFIT %s %0.16g %0.16g", "bx", bx, 0.0) }
if (exists("c_err")) { print sprintf("PYFIT %s %0.16g %0.16g", "c", c, c_err) } else { print sprintf("PYFIT %s %0.16g %0.16g", "c", c, 0.0) }

set output "C:/Projects/Plotinator_10k/outputs/2025-11-15_00-25-23/plot_general/plot.png"
set multiplot layout 1,1 title "general"
set encoding utf8
set title "Dataset" font ",16"
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
plot "C:/Projects/Plotinator_10k/data/sample3.dat" using 1:2 with points title "Dataset" pt 7 lc rgb "#1f77b4", \
+     f(x) title sprintf("ax^2+bx+c") with lines lw 2.0 lc rgb "#1f77b4"
unset multiplot
unset output
