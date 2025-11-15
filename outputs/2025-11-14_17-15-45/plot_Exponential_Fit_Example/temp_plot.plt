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
A = 26.7
B = 53.4

f(x) = A * exp(B * x)
fit f(x) "C:/Projects/Plotinator_10k/outputs/2025-11-14_17-15-45/plot_Exponential_Fit_Example/dataset_1/preprocessed.dat" using 1:2:4 via A,B

if (exists("A_err")) { print sprintf("PYFIT %s %0.16g %0.16g", "A", A, A_err) } else { print sprintf("PYFIT %s %0.16g %0.16g", "A", A, 0.0) }
if (exists("B_err")) { print sprintf("PYFIT %s %0.16g %0.16g", "B", B, B_err) } else { print sprintf("PYFIT %s %0.16g %0.16g", "B", B, 0.0) }

set output "C:/Projects/Plotinator_10k/outputs/2025-11-14_17-15-45/plot_Exponential_Fit_Example/plot.png"
set multiplot layout 2,1 title "Exponential Fit Example"
set encoding utf8
set title "upper" font ",16"
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
plot "C:/Projects/Plotinator_10k/outputs/2025-11-14_17-15-45/plot_Exponential_Fit_Example/dataset_1/preprocessed.dat" using 1:2 with points title "Growth Curve" pt 7 lc rgb "red", \
+     f(x) title sprintf("A * exp(B * x)") with lines lw 2.0 lc rgb "red"
set encoding utf8
set title "Exponential Fit Example — Pane 2" font ",16"
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
plot NaN notitle
unset multiplot
unset output
