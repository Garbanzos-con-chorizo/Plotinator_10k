
set encoding utf8
set terminal pngcairo size 800,600
set title "Exponential Fit Example"
set xlabel "X"
set ylabel "Y"

set fit errorvariables
A = 26.7
B = 53.4

f(x) = A * exp(B * x)
fit f(x) "C:/Users/jacin/Documents/Lab Physics/Plotinator 100000/data/sample2.dat" via A,B

if (exists("A_err")) { print sprintf("PYFIT %s %0.16g %0.16g", "A", A, A_err) } else { print sprintf("PYFIT %s %0.16g %0.16g", "A", A, 0.0) }
if (exists("B_err")) { print sprintf("PYFIT %s %0.16g %0.16g", "B", B, B_err) } else { print sprintf("PYFIT %s %0.16g %0.16g", "B", B, 0.0) }

set output "C:/Users/jacin/Documents/Lab Physics/Plotinator 100000/outputs/2025-11-08_17-20-15/plot_Exponential_Fit_Example/plot.png"
plot "C:/Users/jacin/Documents/Lab Physics/Plotinator 100000/data/sample2.dat" using 1:2:3 with yerrorbars title "Data ±σ" pt 6, \
     f(x) title sprintf("A * exp(B * x)") with lines lw 3 lc rgb "red"
unset output
