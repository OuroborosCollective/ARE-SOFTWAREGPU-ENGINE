// OuroborosCollective. Repository license applies.
// Optional exact-output scheduler: biological architectures are inspiration.
#pragma once
#include "workrooms.hpp"
#include <condition_variable>
#include <functional>
#include <memory>
#include <string>

namespace are::rooms {
struct BioPolicy { const char* name; bool locality,reuse,frontier,checkpoints; };
constexpr BioPolicy bio_policies[]={
    {"baseline",false,false,false,false},
    {"locality",true,false,false,false},
    {"reuse",false,true,false,false},
    {"frontier",false,false,true,false},
    {"checkpoints",false,false,false,true},
    {"combined",true,true,true,true},
    {"without-locality",false,true,true,true},
    {"without-reuse",true,false,true,true},
    {"without-frontier",true,true,false,true},
    {"without-checkpoints",true,true,true,false}
};
inline BioPolicy bio_policy(const std::string& name) {
    for(auto p:bio_policies)if(name==p.name)return p;
    throw std::runtime_error("ROOM_UNKNOWN_POLICY");
}

// Workers sleep between frames/stages; there is no polling or Python callback.
class ResidentWorkers {
    std::mutex mutex_;
    std::condition_variable start_,done_;
    std::vector<std::thread> threads_;
    std::function<void(unsigned)> job_;
    std::exception_ptr error_;
    std::uint64_t generation_=0;
    unsigned pending_=0;
    bool stop_=false;
    void invoke(const std::function<void(unsigned)>& job,unsigned worker) {
        try { require_environment();job(worker); }
        catch(...) { std::lock_guard<std::mutex> lock(mutex_);if(!error_)error_=std::current_exception(); }
    }
    void loop(unsigned worker) {
        std::uint64_t seen=0;
        std::unique_lock<std::mutex> lock(mutex_);
        for(;;) {
            start_.wait(lock,[&]{return stop_ || generation_!=seen;});
            if(stop_)return;
            seen=generation_;
            lock.unlock();invoke(job_,worker);lock.lock();
            if(--pending_==0)done_.notify_one();
        }
    }
    void shutdown() {
        {std::lock_guard<std::mutex> lock(mutex_);stop_=true;}
        start_.notify_all();for(auto& t:threads_)t.join();
    }
public:
    explicit ResidentWorkers(unsigned workers) {
        try {for(unsigned w=1;w<workers;++w)threads_.emplace_back([this,w]{loop(w);});}
        catch(...) {shutdown();throw;}
    }
    ~ResidentWorkers(){shutdown();}
    ResidentWorkers(const ResidentWorkers&)=delete;
    ResidentWorkers& operator=(const ResidentWorkers&)=delete;
    void run(const std::function<void(unsigned)>& job) {
        {std::lock_guard<std::mutex> lock(mutex_);
            job_=job;error_=nullptr;pending_=unsigned(threads_.size());++generation_;}
        start_.notify_all();invoke(job,0);
        std::unique_lock<std::mutex> lock(mutex_);done_.wait(lock,[&]{return pending_==0;});
        job_={};if(error_)std::rethrow_exception(error_);
    }
};

// A ticket is valid for exactly one frame generation and one execution.
// CAS transitions reject duplicate/stale claims and premature completion.
class CheckpointLedger {
    std::size_t count_;
    std::unique_ptr<std::atomic<std::uint64_t>[]> stamps_;
    std::uint64_t epoch_=0;
    std::atomic<std::size_t> completed_{0};
    void valid(std::size_t room,std::uint64_t epoch)const {
        if(room>=count_ || epoch!=epoch_)throw std::runtime_error("ROOM_STALE_TICKET");
    }
public:
    explicit CheckpointLedger(std::size_t count):count_(count),stamps_(new std::atomic<std::uint64_t>[count]) {
        for(std::size_t i=0;i<count_;++i)stamps_[i].store(0,std::memory_order_relaxed);
    }
    std::uint64_t begin() {
        if(epoch_ && completed_.load(std::memory_order_acquire)!=count_)
            throw std::runtime_error("ROOM_UNSEALED_EPOCH");
        if(epoch_==(UINT64_MAX>>2))throw std::runtime_error("ROOM_EPOCH_BUDGET");
        completed_.store(0,std::memory_order_relaxed);return ++epoch_;
    }
    void claim(std::size_t room,std::uint64_t epoch) {
        valid(room,epoch);
        auto expected=epoch==1?0:((epoch-1)<<2)|3;
        if(!stamps_[room].compare_exchange_strong(expected,(epoch<<2)|1,std::memory_order_acq_rel))
            throw std::runtime_error("ROOM_DUPLICATE_TICKET");
        expected=(epoch<<2)|1;
        if(!stamps_[room].compare_exchange_strong(expected,(epoch<<2)|2,std::memory_order_acq_rel))
            throw std::runtime_error("ROOM_BAD_TRANSITION");
    }
    void finish(std::size_t room,std::uint64_t epoch) {
        valid(room,epoch);auto expected=(epoch<<2)|2;
        if(!stamps_[room].compare_exchange_strong(expected,(epoch<<2)|3,std::memory_order_release))
            throw std::runtime_error("ROOM_BAD_TRANSITION");
        completed_.fetch_add(1,std::memory_order_relaxed);
    }
    void require_done(std::size_t room,std::uint64_t epoch)const {
        valid(room,epoch);
        if(stamps_[room].load(std::memory_order_acquire)!=((epoch<<2)|3))
            throw std::runtime_error("ROOM_DEPENDENCY_NOT_READY");
    }
    void seal(std::uint64_t epoch)const {
        if(completed_.load(std::memory_order_acquire)!=count_)
            throw std::runtime_error("ROOM_HANDOFF_INCOMPLETE");
        for(std::size_t i=0;i<count_;++i)require_done(i,epoch);
    }
};

class BioPipeline {
    Pipeline base_;
    BioPolicy policy_;
    std::unique_ptr<ResidentWorkers> resident_;
    std::unique_ptr<CheckpointLedger> ledger_;
    std::unique_ptr<std::atomic<unsigned char>[]> pending_;
    std::uint64_t epoch_=0;
    struct Bounds {int x0,y0,x1,y1;float inv;bool active;};
    std::vector<Bounds> bounds_;
    std::vector<std::size_t> offsets_,cursor_;
    std::vector<std::uint16_t> ids_;
    using Counts=std::array<std::uint64_t,4>;
    std::array<Counts,8> jobs_{};
    std::array<std::uint64_t,8> samples_{};
    template<class F> void neighbors(std::size_t tile,F f)const {
        const auto x=int(tile%base_.tiles_x_),y=int(tile/base_.tiles_x_);
        for(int dy=-1;dy<=1;++dy)for(int dx=-1;dx<=1;++dx)
            if(x+dx>=0 && y+dy>=0 && x+dx<int(base_.tiles_x_) && y+dy<int(base_.tiles_y_))
                f(std::size_t(y+dy)*base_.tiles_x_+std::size_t(x+dx));
    }
    void run_workers(const std::function<void(unsigned)>& job) {
        if(resident_){resident_->run(job);return;}
        std::exception_ptr error;std::mutex mutex;
        auto safe=[&](unsigned w){try{require_environment();job(w);}catch(...){
            std::lock_guard<std::mutex> lock(mutex);if(!error)error=std::current_exception();}};
        std::vector<std::thread> threads;
        try{for(unsigned w=1;w<base_.workers_;++w)threads.emplace_back(safe,w);}
        catch(...){for(auto& t:threads)t.join();throw;}
        safe(0);for(auto& t:threads)t.join();if(error)std::rethrow_exception(error);
    }
    void make_bins() {
        std::fill(offsets_.begin(),offsets_.end(),0);
        for(std::size_t i=0;i<base_.prepared_.size();++i) {
            const auto& t=base_.prepared_[i];const auto& a=t.v[0];const auto& b=t.v[1];const auto& d=t.v[2];
            auto& v=bounds_[i];v={std::max(0,int(std::floor(std::min({a.x,b.x,d.x})))),
                std::max(0,int(std::floor(std::min({a.y,b.y,d.y})))),
                std::min(int(base_.c_.width)-1,int(std::ceil(std::max({a.x,b.x,d.x})))),
                std::min(int(base_.c_.height)-1,int(std::ceil(std::max({a.y,b.y,d.y})))),
                0,t.area>1e-9f};
            v.active=v.active && v.x0<=v.x1 && v.y0<=v.y1;
            if(!v.active)continue;
            v.inv=float(1.0/double(t.area));
            for(int y=v.y0/int(base_.c_.tile);y<=v.y1/int(base_.c_.tile);++y)
                for(int x=v.x0/int(base_.c_.tile);x<=v.x1/int(base_.c_.tile);++x)
                    ++offsets_[std::size_t(y)*base_.tiles_x_+x+1];
        }
        for(std::size_t i=1;i<offsets_.size();++i)offsets_[i]+=offsets_[i-1];
        // Admission already bounds pixels*triangles; no dense room-square matrix.
        if(offsets_.back()>67108864)throw std::runtime_error("ROOM_BIN_BUDGET");
        ids_.resize(offsets_.back());std::copy(offsets_.begin(),offsets_.end()-1,cursor_.begin());
        // Ascending primitive scatter preserves strict-depth first-submission ties.
        for(std::size_t i=0;i<bounds_.size();++i) {
            const auto& v=bounds_[i];if(!v.active)continue;
            for(int y=v.y0/int(base_.c_.tile);y<=v.y1/int(base_.c_.tile);++y)
                for(int x=v.x0/int(base_.c_.tile);x<=v.x1/int(base_.c_.tile);++x) {
                    const auto tile=std::size_t(y)*base_.tiles_x_+x;ids_[cursor_[tile]++]=std::uint16_t(i);
                }
        }
    }
    std::uint64_t raster_local(std::size_t tile) {
        const auto r=base_.rect(tile);std::uint64_t samples=0;base_.clear_samples(r);
        for(auto j=offsets_[tile];j<offsets_[tile+1];++j) {
            const auto id=ids_[j];const auto& t=base_.prepared_[id];const auto& v=bounds_[id];
            const auto x0=std::max<int>(int(r.x0),v.x0),x1=std::min<int>(int(r.x1)-1,v.x1);
            const auto y0=std::max<int>(int(r.y0),v.y0),y1=std::min<int>(int(r.y1)-1,v.y1);
            samples+=base_.raster_samples(r,t,x0,x1,y0,y1,v.inv);
        }
        return samples;
    }
    void visit(unsigned kind,std::size_t i,unsigned worker) {
        const auto n=base_.triangles_.size();const auto room=kind==0?i:n+(kind-1)*base_.tiles_+i;
        if(ledger_) {
            if(kind==2)ledger_->require_done(n+i,epoch_);
            if(kind==3)neighbors(i,[&](auto tile){ledger_->require_done(n+base_.tiles_+tile,epoch_);});
            ledger_->claim(room,epoch_);
        }
        base_.states_[room]=State::ready;base_.states_[room]=State::running;
        switch(static_cast<Kind>(kind)) {
            case Kind::render:base_.render(i);break;
            case Kind::raster:samples_[worker]+=policy_.locality?raster_local(i):base_.raster(i);break;
            case Kind::msaa:base_.msaa(i);break;
            case Kind::aa:base_.aa(i);break;
        }
        base_.states_[room]=State::done;if(ledger_)ledger_->finish(room,epoch_);
        ++jobs_[worker][kind];
    }
    void summarize(unsigned kind,double elapsed) {
        auto& wave=base_.waves_[kind];wave.executed=0;wave.samples=0;wave.milliseconds=elapsed;
        for(unsigned w=0;w<base_.workers_;++w){wave.worker_jobs[w]=jobs_[w][kind];
            wave.executed+=jobs_[w][kind];if(kind==1)wave.samples+=samples_[w];}
        if(wave.executed!=(kind==0?base_.triangles_.size():base_.tiles_))
            throw std::runtime_error("ROOM_INCOMPLETE_WAVE");
    }
    void stage(unsigned kind,std::size_t count) {
        std::atomic<std::size_t> cursor{0};const auto start=std::chrono::steady_clock::now();
        run_workers([&](unsigned w){for(;;){const auto first=cursor.fetch_add(32,std::memory_order_relaxed);
            if(first>=count)break;
            for(auto i=first;i<std::min(first+32,count);++i)visit(kind,i,w);}});
        summarize(kind,std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-start).count());
    }
    void frontier() {
        for(std::size_t i=0;i<base_.tiles_;++i){unsigned char count=0;
            neighbors(i,[&](auto){++count;});pending_[i].store(count,std::memory_order_relaxed);}
        std::atomic<std::size_t> cursor{0};const auto start=std::chrono::steady_clock::now();
        run_workers([&](unsigned w){for(;;){const auto first=cursor.fetch_add(32,std::memory_order_relaxed);
            if(first>=base_.tiles_)break;
            for(auto i=first;i<std::min(first+32,base_.tiles_);++i) {
                visit(1,i,w);visit(2,i,w);
                neighbors(i,[&](auto target){
                    // Each predecessor publishes its entire immutable resolved tile.
                    // The acq_rel RMW chain carries ALL halo writes to the last worker.
                    const auto old=pending_[target].fetch_sub(1,std::memory_order_acq_rel);
                    if(old==0)throw std::runtime_error("ROOM_DUPLICATE_DEPENDENCY");
                    if(old==1)visit(3,target,w);
                });
            }
        }});
        const auto elapsed=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-start).count();
        for(unsigned k=1;k<4;++k)summarize(k,elapsed); // shared interval, never additive
    }
public:
    BioPipeline(Config c,const std::vector<Triangle>& scene,unsigned workers,BioPolicy policy):
        base_(c,scene,workers),policy_(policy) {
        // Accept only the finite named policies, not arbitrary caller boolean combinations.
        const auto admitted=bio_policy(policy.name);
        if(admitted.locality!=policy.locality || admitted.reuse!=policy.reuse ||
           admitted.frontier!=policy.frontier || admitted.checkpoints!=policy.checkpoints)
            throw std::runtime_error("ROOM_POLICY_SCHEMA");
        if(policy.reuse)resident_=std::make_unique<ResidentWorkers>(workers);
        if(policy.checkpoints)ledger_=std::make_unique<CheckpointLedger>(base_.room_count());
        if(policy.frontier)pending_.reset(new std::atomic<unsigned char>[base_.tiles_]);
        if(policy.locality){bounds_.resize(scene.size());offsets_.resize(base_.tiles_+1);cursor_.resize(base_.tiles_);}
        for(auto& wave:base_.waves_)wave.worker_jobs.resize(workers);
    }
    void execute() {
        if(std::string(policy_.name)=="baseline"){base_.execute();return;}
        base_.delivered_=false;require_environment();
        std::fill(base_.states_.begin(),base_.states_.end(),State::waiting);jobs_={};samples_={};
        if(ledger_)epoch_=ledger_->begin();
        stage(0,base_.triangles_.size());
        if(ledger_)for(std::size_t i=0;i<base_.triangles_.size();++i)ledger_->require_done(i,epoch_);
        if(policy_.locality)make_bins(); // recomputed each frame, included in timing
        if(policy_.frontier)frontier();else for(unsigned k=1;k<4;++k)stage(k,base_.tiles_);
        for(auto state:base_.states_)if(state!=State::done)throw std::runtime_error("ROOM_HANDOFF_INCOMPLETE");
        if(ledger_)ledger_->seal(epoch_);
        base_.delivered_=true;
    }
    const auto& rgba()const{return base_.rgba();}
    const auto& resolved()const{return base_.resolved();}
    const auto& depth()const{return base_.depth();}
    const auto& waves()const{return base_.waves();}
    auto room_count()const{return base_.room_count();}
    auto tiles()const{return base_.tiles();}
    auto address(std::size_t room)const{return base_.address(room);}
    std::size_t spatial_references()const{return ids_.size();}
};
} // namespace are::rooms
