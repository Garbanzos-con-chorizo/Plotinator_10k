
set encoding utf8
set terminal pngcairo size 800,600
set title "Linear Fit Example"
set xlabel "X"
set ylabel "Y"

set fit errorvariables
a = 5.0
b = 10.0

f(x) = a*x + b
fit f(x) "C:/Users/jacin/Documents/Lab Physics/Plotinator 100000/data/sample1.dat" via a,b

if (exists("a_err")) { print sprintf("PYFIT %s %0.16g %0.16g", "a", a, a_err) } else { print sprintf("PYFIT %s %0.16g %0.16g", "a", a, 0.0) }
if (exists("b_err")) { print sprintf("PYFIT %s %0.16g %0.16g", "b", b, b_err) } else { print sprintf("PYFIT %s %0.16g %0.16g", "b", b, 0.0) }

set output "None"
plot "C:/Users/jacin/Documents/Lab Physics/Plotinator 100000/data/sample1.dat" using 1:2 title "Data" with points pt 7, \
     f(x) title sprintf("a*x + b") with lines lw 2 lc rgb "blue"
unset output

set output "C:/Users/jacin/Documents/Lab Physics/Plotinator 100000/outputs/2025-11-08_17-20-15/plot_Linear_Fit_Example/residuals.png"
set title "Residuals — Linear Fit Example"
set xlabel "X"
set ylabel "Residual (y - f(x))"
set grid back
plot "C:/Users/jacin/Documents/Lab Physics/Plotinator 100000/data/sample1.dat" using 1:($2 - f($1)) with points pt 7 title "Residuals", \
     0 with lines notitle lc rgb "gray"
unset output
