# OuroborosCollective. Repository license applies.
# CPU-only, independent differential oracle for the EXISTING C++17 wave.
# No packages, GLB publishing, production activation, or GPU claims.
using Test

const PRIME=UInt64(1099511628211)
const OFFSET=UInt64(14695981039346656037)
const ROOT=normpath(joinpath(@__DIR__,"..",".."))

function radial(dx,dy,vx,vy,speed)
    length=hypot(Float64(dx),Float64(dy))
    length>1e-12 || error("invalid LOS")
    component=(vx*dx+vy*dy)/length
    abs(component)<.95*speed || error("invalid speed budget")
    speed/(speed-component)
end

function tint_pixel(color::NTuple{4,Int},factor::Float64,gain)
    tint=clamp((factor-1)*gain,-1.,1.)
    amount=Int(floor(abs(tint)*64+.5))
    r,g,b,a=color
    if tint>0
        r=max(0,r-amount); b=min(255,b+amount)
    elseif tint<0
        r=min(255,r+amount); b=max(0,b-amount)
    end
    (r,g,b,a)
end

function feed_hash(h::UInt64,n::UInt32)
    for k=0:3
        h=(h ⊻ UInt64((n>>(8*k)) & UInt32(255)))*PRIME
    end
    h
end

function independent_wave(mode)
    width=4; height=4; cells=width*height
    seed=UInt32(5) # (x=1,y=1), zero-based
    doppler=mode!="off"
    reuse=mode=="reuse"
    owners=fill(UInt32(7),cells)
    owners[1]=owners[end]=UInt32(0)
    color=[(96,40,128,255) for _=1:cells]
    completed=falses(cells)
    pending=[(time=0.0,cell=seed,emitter=seed)]
    events=NamedTuple[]
    refused=UInt64(0); fingerprint=OFFSET
    tinted=0; evaluations=0
    while !isempty(pending)
        sort!(pending,by=z->(z.time,z.cell,z.emitter),alg=Base.Sort.MergeSort)
        item=popfirst!(pending)
        i=Int(item.cell)+1
        if completed[i]
            refused+=1
            continue
        end
        x=Int(item.cell)%width; y=Int(item.cell)÷width
        px=Int(item.emitter)%width; py=Int(item.emitter)÷width
        factor=1.0
        if doppler && item.cell!=item.emitter
            factor=radial(x-px,y-py,30.,0.,120.)
            evaluations+=1
        end
        recolored=0
        if doppler && owners[i]!=0 && item.cell!=item.emitter
            before=color[i]
            color[i]=tint_pixel(before,factor,1.)
            recolored=before!=color[i] ? 1 : 0
            if !reuse
                evaluations+=1 # reference C++ apply_single_object recomputes factor
            end
        end
        completed[i]=true
        tinted+=recolored
        push!(events,(area=item.cell,emitter=item.emitter,
            arrival=item.time,factor=factor,owner=owners[i],tinted=recolored,
            rgba=color[i]))
        for value in (item.cell,item.emitter,owners[i],UInt32(recolored))
            fingerprint=feed_hash(fingerprint,value)
        end
        for dy=-1:1,dx=-1:1
            (dx==0 && dy==0) && continue
            xx=x+dx; yy=y+dy
            (xx<0 || xx>=width || yy<0 || yy>=height) && continue
            next=UInt32(yy*width+xx)
            if !completed[Int(next)+1]
                distance=(dx!=0 && dy!=0) ? 1.4142135623730950488 : 1.
                push!(pending,(time=item.time+distance/120.,cell=next,emitter=item.cell))
            else
                refused+=1
            end
        end
    end
    (events=events,refused=refused,fingerprint=fingerprint,
        tinted=tinted,evaluations=evaluations)
end

function validate(stdout)
    groups=Dict{String,Vector{Vector{String}}}()
    for line in split(chomp(stdout),'\n')
        fields=split(line,'\t')
        isempty(fields) && continue
        push!(get!(groups,String(fields[1]),Vector{Vector{String}}()),String.(fields))
    end
    @testset "C++ versus independent Julia Doppler" begin
        factors=Dict("toward"=>4/3,"away"=>4/5,"neutral"=>1.,
            "diagonal"=>120/(120-30/sqrt(2)),
            "diagonal_away"=>120/(120+30/sqrt(2)))
        @test length(get(groups,"D",[]))==5
        for row in get(groups,"D",[])
            @test haskey(factors,row[2])
            expected=factors[row[2]]
            @test isapprox(parse(Float64,row[3]),expected;rtol=2e-14,atol=1e-14)
            @test isapprox(parse(Float64,row[4]),expected;rtol=2e-14,atol=1e-14)
            @test isapprox(parse(Float64,row[3]),parse(Float64,row[4]);rtol=2e-14)
        end
        @test length(get(groups,"R",[]))==2
        @test all(row[end]=="1" for row in get(groups,"R",[]))
    end
    @testset "C++ versus independent Julia impact waves" begin
        @test length(get(groups,"W",[]))==48
        @test length(get(groups,"M",[]))==3
        for mode in ("baseline","reuse","off")
            expected=independent_wave(mode)
            native=[r for r in groups["W"] if r[2]==mode]
            @test length(native)==16
            for (row,event) in zip(native,expected.events)
                @test parse(UInt32,row[3])==event.area
                @test parse(UInt32,row[4])==event.emitter
                @test isapprox(parse(Float64,row[5]),event.arrival;rtol=2e-14,atol=1e-14)
                @test isapprox(parse(Float64,row[6]),event.factor;rtol=2e-14,atol=1e-14)
                @test parse(UInt32,row[7])==event.owner
                @test parse(Int,row[8])==event.tinted
                @test ntuple(i->parse(Int,row[8+i]),4)==event.rgba
            end
            metadata=only([r for r in groups["M"] if r[2]==mode])
            @test parse(UInt64,metadata[3])==expected.refused
            @test parse(UInt64,metadata[4])==expected.fingerprint
            @test parse(Int,metadata[5])==expected.tinted
            @test parse(Int,metadata[6])==expected.evaluations
        end
        @test independent_wave("off").tinted==0
        @test independent_wave("baseline").events==independent_wave("reuse").events
    end
end

function main()
    length(ARGS)==1 || error("usage: julia --startup-file=no --project=... julia_cpp_differential.jl <native-binary>")
    exe=abspath(ARGS[1])
    isfile(exe) || error("missing compiled C++ fixture")
    native=read(`$exe`,String)
    validate(native)
    println("JULIA_CPP_DOPPLER_SPHEREPOP_DIFFERENTIAL_PASS")
end
main()
